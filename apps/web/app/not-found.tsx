import Link from "next/link";

export default function NotFound() {
  return (
    <div className="m-6 rounded-md border border-line bg-panel p-4 text-sm">
      <div className="font-medium">Instrument or page not found</div>
      <p className="mt-1 text-muted">Symbols are resolved by type and exchange. Try the search bar (press /).</p>
      <Link href="/dashboard" className="mt-3 inline-block text-accent hover:underline">
        Back to market overview
      </Link>
    </div>
  );
}
