import { Providers } from './providers';
import { Header } from '@/components/Header';

export default function Home() {
  return (
    <Providers>
      <div className="min-h-screen bg-background">
        <Header />
        <main className="container mx-auto px-4 py-8">
          <div className="text-center mb-12">
            <h1 className="text-5xl font-bold mb-4">Kotodama (言霊)</h1>
            <p className="text-xl text-muted-foreground mb-8">
              Modular Multi-Agent Game Generation Service
            </p>
            <p className="text-lg text-muted-foreground">
              Create unique games powered by AI agents and your imagination
            </p>
          </div>
          
          <div className="grid md:grid-cols-3 gap-6 max-w-6xl mx-auto">
            <a 
              href="/wizard"
              className="p-6 border rounded-lg hover:bg-accent transition-colors"
            >
              <h3 className="text-xl font-semibold mb-2">🎮 New Game Wizard</h3>
              <p className="text-muted-foreground">
                Step-by-step game creation with 14 configuration steps
              </p>
            </a>
            
            <a 
              href="/lore"
              className="p-6 border rounded-lg hover:bg-accent transition-colors"
            >
              <h3 className="text-xl font-semibold mb-2">📚 Lore Manager</h3>
              <p className="text-muted-foreground">
                Create and manage your universes, characters, and world rules
              </p>
            </a>
            
            <a 
              href="/projects"
              className="p-6 border rounded-lg hover:bg-accent transition-colors"
            >
              <h3 className="text-xl font-semibold mb-2">📁 My Projects</h3>
              <p className="text-muted-foreground">
                View and manage your generated games
              </p>
            </a>
          </div>
        </main>
      </div>
    </Providers>
  );
}
