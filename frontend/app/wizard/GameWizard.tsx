'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { ChevronLeft, ChevronRight, Check } from 'lucide-react';
import { GenreStep } from './steps/GenreStep';
import { PerspectiveStep } from './steps/PerspectiveStep';
import { ArtStyleStep } from './steps/ArtStyleStep';
import { SettingStep } from './steps/SettingStep';
import { ScaleStep } from './steps/ScaleStep';
import { ControlsStep } from './steps/ControlsStep';
import { SavingStep } from './steps/SavingStep';
import { MonetizationStep } from './steps/MonetizationStep';
import { QuestComplexityStep } from './steps/QuestComplexityStep';
import { DialogueDepthStep } from './steps/DialogueDepthStep';
import { LoreStep } from './steps/LoreStep';
import { DescriptionStep } from './steps/DescriptionStep';
import { ConfirmationStep } from './steps/ConfirmationStep';
import { PreviewWarningStep } from './steps/PreviewWarningStep';

const stepTitles = [
  'Choose Genre',
  'Select Perspective',
  'Pick Art Style',
  'Define Setting',
  'Set Scale',
  'Configure Controls',
  'Save System',
  'Monetization',
  'Quest Complexity',
  'Dialogue Depth',
  'Select Lore',
  'Describe Your Game',
  'Review & Confirm',
  'Live Preview',
];

export function GameWizard() {
  const { currentStep, nextStep, prevStep, setStep } = useWizardStore();

  const renderStep = () => {
    switch (currentStep) {
      case 1: return <GenreStep />;
      case 2: return <PerspectiveStep />;
      case 3: return <ArtStyleStep />;
      case 4: return <SettingStep />;
      case 5: return <ScaleStep />;
      case 6: return <ControlsStep />;
      case 7: return <SavingStep />;
      case 8: return <MonetizationStep />;
      case 9: return <QuestComplexityStep />;
      case 10: return <DialogueDepthStep />;
      case 11: return <LoreStep />;
      case 12: return <DescriptionStep />;
      case 13: return <ConfirmationStep />;
      case 14: return <PreviewWarningStep />;
      default: return <GenreStep />;
    }
  };

  const canProceed = () => {
    // Add validation logic per step
    return true;
  };

  return (
    <div className="max-w-4xl mx-auto">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between mb-4">
            <CardTitle>Step {currentStep} of 14</CardTitle>
            <span className="text-sm text-muted-foreground">
              {stepTitles[currentStep - 1]}
            </span>
          </div>
          <Progress value={(currentStep / 14) * 100} className="h-2" />
        </CardHeader>
        
        <CardContent>
          <div className="min-h-[400px]">
            {renderStep()}
          </div>
          
          <div className="flex justify-between mt-8">
            <Button
              variant="outline"
              onClick={prevStep}
              disabled={currentStep === 1}
              className="gap-2"
            >
              <ChevronLeft className="w-4 h-4" />
              Previous
            </Button>
            
            {currentStep < 14 ? (
              <Button
                onClick={nextStep}
                disabled={!canProceed()}
                className="gap-2"
              >
                Next
                <ChevronRight className="w-4 h-4" />
              </Button>
            ) : (
              <Button className="gap-2 bg-green-600 hover:bg-green-700">
                <Check className="w-4 h-4" />
                Start Generation
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
