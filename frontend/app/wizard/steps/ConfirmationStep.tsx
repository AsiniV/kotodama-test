'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react';
import { useState } from 'react';
import { api, WizardInput } from '@/lib/api';

export function ConfirmationStep() {
  const { 
    genre, perspective, artStyle, setting, scale, controls,
    savingEnabled, monetization, questComplexity, dialogueDepth,
    loreId, description, reset
  } = useWizardStore();

  const [isGenerating, setIsGenerating] = useState(false);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);

  const summary = [
    { label: 'Genre', value: genre },
    { label: 'Perspective', value: perspective },
    { label: 'Art Style', value: artStyle },
    { label: 'Setting', value: setting },
    { label: 'Scale', value: scale },
    { label: 'Controls', value: controls },
    { label: 'Save System', value: savingEnabled ? 'Enabled' : 'Disabled' },
    { label: 'Monetization', value: monetization },
    { label: 'Quest Complexity', value: questComplexity },
    { label: 'Dialogue Depth', value: dialogueDepth },
    { label: 'Lore', value: loreId || 'None' },
  ];

  const estimatedCredits = 10; // Base cost
  const estimatedTime = '3-5 minutes';

  const handleStartGeneration = async () => {
    if (!genre || !perspective || !artStyle) {
      setGenerationError('Please complete all required steps');
      return;
    }

    setIsGenerating(true);
    setGenerationError(null);

    try {
      const wizardInput: WizardInput = {
        genre: genre!,
        perspective: perspective!,
        art_style: artStyle!,
        setting: setting!,
        scale: scale!,
        controls: controls!,
        saving_enabled: savingEnabled,
        monetization: monetization!,
        quest_complexity: questComplexity,
        dialogue_depth: dialogueDepth,
        lore_id: loreId,
        description: description,
      };

      const result = await api.startGeneration(wizardInput);
      setProjectId(result.project_id);
      
      // Navigate to preview step or status page
      // For now, we'll just show success message
      alert(`Generation started! Project ID: ${result.project_id}\nEstimated time: ${result.estimated_time_seconds}s\nCredits: ${result.estimated_credits}`);
    } catch (error) {
      setGenerationError(error instanceof Error ? error.message : 'Failed to start generation');
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle>Review & Confirm</CardTitle>
        <CardDescription>
          Review your game configuration before generation
        </CardDescription>
      </CardHeader>
      
      <CardContent className="space-y-6">
        <div className="space-y-3">
          <h4 className="font-semibold">Configuration Summary:</h4>
          <div className="grid grid-cols-2 gap-3">
            {summary.map((item) => (
              <div key={item.label} className="flex justify-between items-center p-2 bg-muted rounded">
                <span className="text-sm text-muted-foreground">{item.label}</span>
                <Badge variant="secondary">{item.value || 'Not set'}</Badge>
              </div>
            ))}
          </div>
        </div>

        {description && (
          <div className="space-y-2">
            <h4 className="font-semibold">Your Description:</h4>
            <p className="text-sm text-muted-foreground bg-muted p-3 rounded">
              {description.length > 200 ? `${description.substring(0, 200)}...` : description}
            </p>
          </div>
        )}

        <div className="border-t pt-4 space-y-3">
          <div className="flex justify-between items-center">
            <span className="font-semibold">Estimated Cost:</span>
            <Badge variant="default" className="text-lg px-3 py-1">
              {estimatedCredits} credits
            </Badge>
          </div>
          <div className="flex justify-between items-center">
            <span className="font-semibold">Estimated Time:</span>
            <Badge variant="outline">{estimatedTime}</Badge>
          </div>
        </div>

        <div className="bg-amber-50 border border-amber-200 p-4 rounded-lg flex gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="text-sm font-medium text-amber-800">
              Important Notes:
            </p>
            <ul className="text-xs text-amber-700 space-y-1 list-disc list-inside">
              <li>First attempt is FREE if it fails (automatic rollback)</li>
              <li>Second attempt will be charged even if it fails</li>
              <li>Generated assets are preserved across retries</li>
              <li>Live preview takes ~30 seconds to build and load</li>
            </ul>
          </div>
        </div>

        {generationError && (
          <div className="bg-red-50 border border-red-200 p-4 rounded-lg">
            <p className="text-sm font-medium text-red-800">Error: {generationError}</p>
          </div>
        )}

        {projectId && (
          <div className="bg-green-50 border border-green-200 p-4 rounded-lg">
            <p className="text-sm font-medium text-green-800">✓ Generation started! Project ID: {projectId}</p>
          </div>
        )}
      </CardContent>
    </div>
  );
}
