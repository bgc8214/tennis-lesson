/**
 * 17문서 U-1: 브라우저에서 영상 파일의 오디오만 추출하는 공용 유틸.
 *
 * U-0 실측(6.3GB 영상도 3.8초에 추출 성공)에서 확정한 방식을 그대로 사용:
 * fetchFile()+writeFile()은 파일 전체를 메모리(ArrayBuffer)로 복사해 6GB급에서
 * FileReader가 실패(Code=-1)한다. WORKERFS 마운트는 File 객체를 가상 FS에
 * 스트리밍으로 노출해 메모리 통복사가 없다 — 반드시 이 방식을 유지할 것.
 */

let ffmpegSingleton: import("@ffmpeg/ffmpeg").FFmpeg | null = null;

export type ExtractPhase = "loading-ffmpeg" | "extracting";

export interface ExtractProgress {
  phase: ExtractPhase;
  message: string;
}

export interface ExtractedAudio {
  /** 추출된 오디오 바이트 (m4a demux copy, 폴백 시 aac 재인코딩) */
  data: Uint8Array;
  /** demux(copy)로 무손실 추출됐는지. false면 aac 재인코딩 폴백 사용 */
  copyOk: boolean;
  reencodeUsed: boolean;
  /** 추출(mount~read) 소요 시간(ms) */
  extractMs: number;
  outputSizeBytes: number;
}

/** FFmpeg.wasm을 지연 로드(첫 호출만 수 MB 다운로드). 인스턴스는 재사용. */
async function ensureFfmpegLoaded(
  onProgress?: (p: ExtractProgress) => void,
): Promise<import("@ffmpeg/ffmpeg").FFmpeg> {
  if (ffmpegSingleton) return ffmpegSingleton;

  onProgress?.({
    phase: "loading-ffmpeg",
    message: "FFmpeg.wasm 로딩 중... (첫 실행은 수 MB 다운로드)",
  });

  const { FFmpeg } = await import("@ffmpeg/ffmpeg");
  const { toBlobURL } = await import("@ffmpeg/util");

  const ffmpeg = new FFmpeg();
  ffmpeg.on("log", ({ message }) => {
    onProgress?.({ phase: "extracting", message });
  });

  const baseURL = "https://unpkg.com/@ffmpeg/core@0.12.6/dist/esm";
  await ffmpeg.load({
    coreURL: await toBlobURL(`${baseURL}/ffmpeg-core.js`, "text/javascript"),
    wasmURL: await toBlobURL(`${baseURL}/ffmpeg-core.wasm`, "application/wasm"),
    // Next.js webpack이 @ffmpeg/ffmpeg의 기본 worker.js를 번들링하면서 상대 경로
    // import가 깨짐 — public/에 정적 복사 + 절대 URL로 지정.
    classWorkerURL: new URL("/ffmpeg/worker.js", window.location.origin).toString(),
  });

  ffmpegSingleton = ffmpeg;
  return ffmpeg;
}

/**
 * 영상 File에서 오디오만 추출한다. demux(-vn -acodec copy)를 우선 시도하고,
 * 컨테이너가 copy를 거부하면 aac 128k 재인코딩으로 폴백한다.
 *
 * @throws 추출 자체가 실패하면 Error (호출 측에서 "지원하지 않는 형식" 안내).
 */
export async function extractAudioFromVideo(
  file: File,
  onProgress?: (p: ExtractProgress) => void,
): Promise<ExtractedAudio> {
  const ffmpeg = await ensureFfmpegLoaded(onProgress);
  const { FFFSType } = await import("@ffmpeg/ffmpeg");

  const mountDir = "/input_mount";
  const outputName = "output.m4a";

  onProgress?.({ phase: "extracting", message: "오디오 추출 중 (재인코딩 없는 demux)..." });

  const t0 = performance.now();
  await ffmpeg.createDir(mountDir);
  await ffmpeg.mount(FFFSType.WORKERFS, { files: [file] }, mountDir);

  try {
    let copyOk = false;
    let reencodeUsed = false;
    // ffmpeg.exec()는 예외를 던지지 않고 종료 코드(0=성공, !=0=실패)를 반환한다 —
    // 코드를 직접 확인해야 실패를 감지할 수 있다(과거 항상 copyOk=true로 오판되어
    // 폴백이 전혀 실행되지 않고 존재하지 않는 출력 파일 readFile에서 에러가 났었음).
    try {
      const copyExit = await ffmpeg.exec(["-i", `${mountDir}/${file.name}`, "-vn", "-acodec", "copy", outputName]);
      copyOk = copyExit === 0;
    } catch {
      copyOk = false;
    }

    if (!copyOk) {
      reencodeUsed = true;
      try {
        await ffmpeg.deleteFile(outputName);
      } catch {
        // copy 시도가 부분 파일을 남겼을 수 있으니 재인코딩 전에 정리 (없으면 무시)
      }
      onProgress?.({ phase: "extracting", message: "demux 실패 → aac 재인코딩 폴백 중..." });
      const reencodeExit = await ffmpeg.exec([
        "-i", `${mountDir}/${file.name}`, "-vn", "-acodec", "aac", "-b:a", "128k", outputName,
      ]);
      if (reencodeExit !== 0) {
        throw new Error(`오디오 재인코딩 실패 (exit ${reencodeExit})`);
      }
    }

    const extractMs = performance.now() - t0;
    const raw = (await ffmpeg.readFile(outputName)) as Uint8Array;
    // FS에서 읽은 뷰가 내부 힙(SharedArrayBuffer일 수 있음)을 참조하므로,
    // 독립 ArrayBuffer 복사본으로 확보 — Blob/digest에 안전하게 넘기기 위함.
    const data = new Uint8Array(new ArrayBuffer(raw.byteLength));
    data.set(raw);

    return {
      data,
      copyOk,
      reencodeUsed,
      extractMs,
      outputSizeBytes: data.byteLength,
    };
  } finally {
    try {
      await ffmpeg.unmount(mountDir);
    } catch {
      // ignore
    }
    try {
      await ffmpeg.deleteFile(outputName);
    } catch {
      // ignore
    }
  }
}

/** 추출된 오디오(메모리에 있는 작은 결과물)의 SHA-256 16진 해시.
 * 원본 영상(수 GB)을 해시하면 메모리 문제가 재발하므로 반드시 오디오만 해시. */
export async function sha256Hex(data: Uint8Array): Promise<string> {
  // data.byteLength 크기의 독립 ArrayBuffer 복사본을 만들어 넘긴다
  // (WORKERFS/WASM 힙 뷰가 SharedArrayBuffer일 수 있어 digest에 직접 못 넘김).
  const buf = new ArrayBuffer(data.byteLength);
  new Uint8Array(buf).set(data);
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** 영상 File의 재생 길이(초)를 <video> 메타데이터로 프로브. 실패 시 null. */
export function probeVideoDuration(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const video = document.createElement("video");
    video.preload = "metadata";
    video.muted = true;
    const url = URL.createObjectURL(file);
    const cleanup = () => URL.revokeObjectURL(url);
    const timeout = setTimeout(() => {
      cleanup();
      resolve(null);
    }, 8000);
    video.onloadedmetadata = () => {
      clearTimeout(timeout);
      const dur = Number.isFinite(video.duration) ? video.duration : null;
      cleanup();
      resolve(dur);
    };
    video.onerror = () => {
      clearTimeout(timeout);
      cleanup();
      resolve(null);
    };
    video.src = url;
  });
}
