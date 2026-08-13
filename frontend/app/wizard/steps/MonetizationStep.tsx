'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

const monetizationOptions = [
  { id: 'none', name: 'None', description: 'No monetization, free game' },
  { id: 'premium', name: 'Premium', description: 'One-time purchase' },
  { id: 'ads', name: 'Ads', description: 'Interstitial or rewarded ads' },
  { id: 'iap', name: 'In-App Purchases', description: 'Buy items, cosmetics, or content' },
  { id: 'subscription', name: 'Subscription', description: 'Recurring payment for access' },
];

export function MonetizationStep() {
  const { monetization, setMonetization } = useWizardStore();

  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle>Monetization Model</CardTitle>
        <CardDescription>
          Choose how your game will generate revenue (if any)
        </CardDescription>
      </CardHeader>
      
      <CardContent>
        <div className="grid grid-cols-2 gap-4">
          {monetizationOptions.map((m) => (
            <Button
              key={m.id}
              variant={monetization === m.id ? 'default' : 'outline'}
              className={`h-auto py-4 px-4 flex flex-col items-start gap-2 ${
                monetization === m.id ? 'ring-2 ring-primary' : ''
              }`}
              onClick={() => setMonetization(m.id)}
            >
              <span className="font-semibold">{m.name}</span>
              <span className="text-xs text-muted-foreground text-left">
                {m.description}
              </span>
            </Button>
          ))}
        </div>
      </CardContent>
    </div>
  );
}
