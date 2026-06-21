import Link from "next/link";

export function Header() {
  return (
    <header className="sticky top-0 z-40 border-b border-gray-100 bg-white/85 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-6xl items-center px-4 sm:h-16 sm:px-6">
        <Link
          href="/"
          className="group flex items-center gap-2 font-bold tracking-tight"
        >
          <span
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500 text-white shadow-sm transition group-hover:bg-brand-600"
            aria-hidden
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="currentColor"
              className="h-5 w-5"
            >
              <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2Zm0 18a8 8 0 0 1-7.43-5h2.06a6 6 0 0 0 10.74 0h2.06A8 8 0 0 1 12 20Zm-7.43-9a8 8 0 0 1 14.86 0h-2.06a6 6 0 0 0-10.74 0Z" />
            </svg>
          </span>
          <span className="text-base sm:text-lg">오늘의 테니스</span>
        </Link>
      </div>
    </header>
  );
}
