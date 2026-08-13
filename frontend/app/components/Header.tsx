import Link from 'next/link';
import { Gamepad2, Library, FolderOpen, User } from 'lucide-react';

export function Header() {
  return (
    <header className="border-b">
      <div className="container mx-auto px-4 py-4 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 text-xl font-bold">
          <Gamepad2 className="w-6 h-6" />
          <span>Kotodama</span>
        </Link>
        
        <nav className="flex items-center gap-6">
          <Link href="/wizard" className="flex items-center gap-2 hover:text-primary transition-colors">
            <Gamepad2 className="w-4 h-4" />
            <span>Wizard</span>
          </Link>
          <Link href="/lore" className="flex items-center gap-2 hover:text-primary transition-colors">
            <Library className="w-4 h-4" />
            <span>Lore</span>
          </Link>
          <Link href="/projects" className="flex items-center gap-2 hover:text-primary transition-colors">
            <FolderOpen className="w-4 h-4" />
            <span>Projects</span>
          </Link>
          <Link href="/profile" className="flex items-center gap-2 hover:text-primary transition-colors">
            <User className="w-4 h-4" />
            <span>Profile</span>
          </Link>
        </nav>
      </div>
    </header>
  );
}
