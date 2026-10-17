import Link from 'next/link';
import { FolderOpen, Gamepad2, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export default function ProjectsPage() {
  return (
    <main className="min-h-screen p-6">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Projects</h1>
            <p className="text-muted-foreground">Generated games and active generations</p>
          </div>
          <Button asChild>
            <Link href="/wizard">
              <Plus className="mr-2 h-4 w-4" />
              New Game
            </Link>
          </Button>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FolderOpen className="h-5 w-5" />
              No projects yet
            </CardTitle>
            <CardDescription>
              Start the 14-step wizard to generate your first game with the multi-agent pipeline.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Gamepad2 className="h-4 w-4" />
              Project statuses:
              <Badge variant="outline">draft</Badge>
              <Badge variant="outline">generating</Badge>
              <Badge variant="outline">ready</Badge>
              <Badge variant="outline">failed</Badge>
              <Badge variant="outline">archived</Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              List endpoint: <code>GET /api/v1/generation/projects</code>
            </p>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
