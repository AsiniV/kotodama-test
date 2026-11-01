/**
 * Клиентский доступ к REST API бэкенда (FastAPI).
 *
 * В dev-режиме запросы идут на "/api/..." и проксируются через rewrites
 * в next.config.js на http://localhost:8000.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? '/api/v1';

export interface WizardInput {
  genre: string;
  perspective: string;
  art_style: string;
  setting: string;
  scale: string;
  controls: Record<string, unknown>;
  has_saving: boolean;
  monetization?: string | null;
  quest_complexity: 'none' | 'simple' | 'branching' | 'epic';
  dialogue_depth: 'none' | 'linear' | 'branching' | 'full_rpg';
  lore_collection_id?: number | null;
  text_description: string;
  project_name: string;
}

export interface GenerationResponse {
  success: boolean;
  project_id: string;
  message: string;
  estimated_time_seconds: number;
  estimated_credits: number;
}

export interface ProjectStatusResponse {
  project_id: string;
  status: string; // pending, running, completed, failed
  progress: number; // 0-100
  current_agent?: string | null;
  logs: string[];
  attempt_number: number;
  result?: Record<string, unknown> | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail =
          typeof body.detail === 'string'
            ? body.detail
            : JSON.stringify(body.detail);
      }
    } catch {
      // тело ответа не является JSON — используем статус как сообщение
    }
    throw new Error(detail);
  }

  return (await res.json()) as T;
}

export const api = {
  /** Запуск генерации игры по результатам мастера (POST /generation/start). */
  startGeneration(input: WizardInput): Promise<GenerationResponse> {
    return request<GenerationResponse>('/generation/start', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  /** Статус генерации проекта (GET /generation/status/{projectId}). */
  getGenerationStatus(projectId: string): Promise<ProjectStatusResponse> {
    return request<ProjectStatusResponse>(`/generation/status/${projectId}`);
  },
};
