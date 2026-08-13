'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Save } from 'lucide-react';

export function SavingStep() {
  const { savingEnabled, setSavingEnabled } = useWizardStore();

  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle>Save System</CardTitle>
        <CardDescription>
          Enable automatic save/load functionality for your game
        </CardDescription>
      </CardHeader>
      
      <CardContent>
        <div className="flex flex-col items-center gap-6 py-8">
          <Save className="w-24 h-24 text-primary" />
          
          <p className="text-center text-muted-foreground max-w-md">
            When enabled, the system will automatically generate a complete save/load 
            module that persists player progress, inventory, quest states, and dialogue flags.
          </p>
          
          <div className="flex gap-4">
            <Button
              variant={savingEnabled ? 'outline' : 'default'}
              size="lg"
              onClick={() => setSavingEnabled(false)}
              className={!savingEnabled ? 'ring-2 ring-primary' : ''}
            >
              No Save System
            </Button>
            
            <Button
              variant={savingEnabled ? 'default' : 'outline'}
              size="lg"
              onClick={() => setSavingEnabled(true)}
              className={savingEnabled ? 'ring-2 ring-primary' : ''}
            >
              Enable Save/Load
            </Button>
          </div>
          
          {savingEnabled && (
            <div className="mt-4 p-4 bg-muted rounded-lg">
              <h4 className="font-semibold mb-2">Included Features:</h4>
              <ul className="text-sm text-muted-foreground space-y-1">
                <li>• Automatic JSON save files</li>
                <li>• Player position and state</li>
                <li>• Inventory serialization</li>
                <li>• Quest progress tracking</li>
                <li>• Dialogue flag persistence</li>
                <li>• World state preservation</li>
              </ul>
            </div>
          )}
        </div>
      </CardContent>
    </div>
  );
}
