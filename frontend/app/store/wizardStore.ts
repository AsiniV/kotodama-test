import { create } from 'zustand';

export interface WizardState {
  currentStep: number;
  genre: string | null;
  perspective: string | null;
  artStyle: string | null;
  setting: string | null;
  scale: string | null;
  controls: string | null;
  savingEnabled: boolean;
  monetization: string | null;
  questComplexity: 'none' | 'simple' | 'branching' | 'epic';
  dialogueDepth: 'none' | 'linear' | 'branching' | 'full_rpg';
  loreId: string | null;
  description: string;
  
  setStep: (step: number) => void;
  nextStep: () => void;
  prevStep: () => void;
  setGenre: (genre: string) => void;
  setPerspective: (perspective: string) => void;
  setArtStyle: (artStyle: string) => void;
  setSetting: (setting: string) => void;
  setScale: (scale: string) => void;
  setControls: (controls: string) => void;
  setSavingEnabled: (enabled: boolean) => void;
  setMonetization: (monetization: string) => void;
  setQuestComplexity: (complexity: 'none' | 'simple' | 'branching' | 'epic') => void;
  setDialogueDepth: (depth: 'none' | 'linear' | 'branching' | 'full_rpg') => void;
  setLoreId: (loreId: string | null) => void;
  setDescription: (description: string) => void;
  reset: () => void;
}

const initialState: Omit<WizardState, keyof Pick<WizardState, 'setStep' | 'nextStep' | 'prevStep' | 'setGenre' | 'setPerspective' | 'setArtStyle' | 'setSetting' | 'setScale' | 'setControls' | 'setSavingEnabled' | 'setMonetization' | 'setQuestComplexity' | 'setDialogueDepth' | 'setLoreId' | 'setDescription' | 'reset'> = {
  currentStep: 1,
  genre: null,
  perspective: null,
  artStyle: null,
  setting: null,
  scale: null,
  controls: null,
  savingEnabled: false,
  monetization: null,
  questComplexity: 'none',
  dialogueDepth: 'none',
  loreId: null,
  description: '',
};

export const useWizardStore = create<WizardState>((set, get) => ({
  ...initialState as WizardState,
  
  setStep: (step) => set({ currentStep: step }),
  
  nextStep: () => {
    const { currentStep } = get();
    if (currentStep < 14) {
      set({ currentStep: currentStep + 1 });
    }
  },
  
  prevStep: () => {
    const { currentStep } = get();
    if (currentStep > 1) {
      set({ currentStep: currentStep - 1 });
    }
  },
  
  setGenre: (genre) => set({ genre }),
  setPerspective: (perspective) => set({ perspective }),
  setArtStyle: (artStyle) => set({ artStyle }),
  setSetting: (setting) => set({ setting }),
  setScale: (scale) => set({ scale }),
  setControls: (controls) => set({ controls }),
  setSavingEnabled: (enabled) => set({ savingEnabled: enabled }),
  setMonetization: (monetization) => set({ monetization }),
  setQuestComplexity: (complexity) => set({ questComplexity: complexity }),
  setDialogueDepth: (depth) => set({ dialogueDepth: depth }),
  setLoreId: (loreId) => set({ loreId }),
  setDescription: (description) => set({ description }),
  
  reset: () => set(initialState as WizardState),
}));
