'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { AlertTriangle, Clock, Loader2 } from 'lucide-react';

export function PreviewWarningStep() {
  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <AlertTriangle className="w-6 h-6 text-amber-500" />
          Live Preview Warning
        </CardTitle>
        <CardDescription>
          Important information about the preview process
        </CardDescription>
      </CardHeader>
      
      <CardContent className="space-y-6">
        <div className="bg-amber-50 border border-amber-200 p-6 rounded-lg space-y-4">
          <div className="flex items-start gap-3">
            <Clock className="w-6 h-6 text-amber-600 flex-shrink-0 mt-0.5" />
            <div>
              <h4 className="font-semibold text-amber-800">
                ⚠️ Building and loading the web version takes about 30 seconds.
              </h4>
              <p className="text-sm text-amber-700 mt-1">
                Enjoy the process of creating magic! The system is compiling your game, 
                running AI playtests, and preparing the live preview.
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <h4 className="font-semibold">What happens during preview:</h4>
          <ol className="space-y-3">
            {[
              'Godot exports your game to WebAssembly',
              'AI Playtester runs automated tests',
              'Assets are optimized for web delivery',
              'Preview server starts and loads your game',
              'You can interact with your creation in real-time'
            ].map((step, i) => (
              <li key={i} className="flex items-center gap-3 text-sm">
                <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center text-primary font-semibold text-xs">
                  {i + 1}
                </div>
                {step}
              </li>
            ))}
          </ol>
        </div>

        <div className="bg-blue-50 border border-blue-200 p-4 rounded-lg">
          <h4 className="font-semibold text-blue-800 mb-2">💡 Pro Tips:</h4>
          <ul className="text-sm text-blue-700 space-y-1 list-disc list-inside">
            <li>You can continue browsing while the preview builds</li>
            <li>WebSocket logs will stream generation progress in real-time</li>
            <li>If preview fails, check the error logs for debugging</li>
            <li>Download options (Web/APK) will be available after successful generation</li>
          </ul>
        </div>
      </CardContent>
    </div>
  );
}
