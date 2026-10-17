import Link from 'next/link';
import { Book, Library, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export default function LorePage() {
  return (
    <main className="min-h-screen p-6">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Lore Library</h1>
            <p className="text-muted-foreground">
              Your knowledge base for AI-powered game generation (RAG)
            </p>
          </div>
          <Button asChild>
            <Link href="/lore/new">
              <Plus className="mr-2 h-4 w-4" />
              New Collection
            </Link>
          </Button>
        </div>

        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Library className="h-5 w-5" />
                Getting Started
              </CardTitle>
              <CardDescription>
                No lore collections yet. Create your first collection to give the AI agents
                context about your game universe.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ol className="list-decimal space-y-2 pl-4 text-sm text-muted-foreground">
                <li>Create a lore collection (universe setting)</li>
                <li>Add entries: characters, locations, items, story beats</li>
                <li>Entries are embedded via PGVector for RAG retrieval</li>
                <li>Select the collection in the Game Wizard (step &quot;Lore&quot;)</li>
              </ol>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Book className="h-5 w-5" />
                API
              </CardTitle>
              <CardDescription>Lore endpoints are served by the FastAPI backend</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <Badge variant="outline">GET /api/v1/lore/collections</Badge>{' '}
              <Badge variant="outline">POST /api/v1/lore/collections</Badge>{' '}
              <Badge variant="outline">POST /api/v1/lore/entries</Badge>{' '}
              <Badge variant="outline">POST /api/v1/lore/search</Badge>
            </CardContent>
          </Card>
        </div>
      </div>
    </main>
  );
}
