import { User } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export default function ProfilePage() {
  return (
    <main className="min-h-screen p-6">
      <div className="mx-auto max-w-3xl">
        <h1 className="mb-6 text-3xl font-bold">Profile</h1>

        <div className="grid gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <User className="h-5 w-5" />
                Account
              </CardTitle>
              <CardDescription>
                Sign-in is handled by the backend auth API (JWT). After authentication your
                credits and role will appear here.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2 text-sm">
              <Badge variant="outline">role: user</Badge>
              <Badge variant="outline">credits: —</Badge>
              <Badge variant="outline">plan: free</Badge>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Credits &amp; Pricing</CardTitle>
              <CardDescription>Cost of generation per feature</CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1 text-sm text-muted-foreground">
                <li>Simple game: 10 credits</li>
                <li>Complex game: 25 credits</li>
                <li>Epic quests: +15 credits</li>
                <li>Full RPG dialogues: +15 credits</li>
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </main>
  );
}
