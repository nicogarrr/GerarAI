'use server';
import { askResearchAssistant } from '@/lib/research/assistant-client';
import type { AssistantRequest } from '@/lib/research/assistant-contract';

export async function askResearchAssistantAction(request: AssistantRequest) {
  return askResearchAssistant(request);
}
