/* =============================================
   JARVIS — Type Definitions & State Configuration
   ============================================= */

export type AssistantState =
  | 'IDLE'
  | 'CONNECTING'
  | 'LISTENING'
  | 'THINKING'
  | 'SPEAKING'
  | 'MUTED'
  | 'ERROR';

export interface TranscriptMessage {
  id: string;
  role: 'user' | 'jarvis';
  content: string;
  timestamp: number;
}

export interface StateConfig {
  label: string;
  color: string;
  rgb: [number, number, number];
  description: string;
  ringSpeed: number;
  particleCount: number;
  pulseIntensity: number;
  coreScale: number;
}

export const STATE_CONFIGS: Record<AssistantState, StateConfig> = {
  IDLE: {
    label: 'JARVIS OFFLINE',
    color: '#4a8fa8',
    rgb: [74, 143, 168],
    description: 'Tap the mic to start a session',
    ringSpeed: 0.2,
    particleCount: 12,
    pulseIntensity: 0.3,
    coreScale: 0.7,
  },
  CONNECTING: {
    label: 'CONNECTING',
    color: '#d4a020',
    rgb: [212, 160, 32],
    description: 'Linking to the AI service\u2026',
    ringSpeed: 0.6,
    particleCount: 16,
    pulseIntensity: 0.6,
    coreScale: 0.8,
  },
  LISTENING: {
    label: 'LISTENING',
    color: '#00d4ff',
    rgb: [0, 212, 255],
    description: 'Speak now \u00b7 tap the mic to mute',
    ringSpeed: 0.5,
    particleCount: 20,
    pulseIntensity: 0.7,
    coreScale: 1.0,
  },
  THINKING: {
    label: 'THINKING',
    color: '#7c6cff',
    rgb: [124, 108, 255],
    description: 'Working on it\u2026',
    ringSpeed: 1.2,
    particleCount: 24,
    pulseIntensity: 0.5,
    coreScale: 0.85,
  },
  SPEAKING: {
    label: 'SPEAKING',
    color: '#00d4ff',
    rgb: [0, 212, 255],
    description: 'Tap the mic to interrupt',
    ringSpeed: 0.4,
    particleCount: 28,
    pulseIntensity: 0.9,
    coreScale: 1.1,
  },
  MUTED: {
    label: 'MUTED',
    color: '#2a8a8a',
    rgb: [42, 138, 138],
    description: 'Microphone muted',
    ringSpeed: 0.15,
    particleCount: 8,
    pulseIntensity: 0.2,
    coreScale: 0.75,
  },
  ERROR: {
    label: 'CONNECTION ERROR',
    color: '#ef4444',
    rgb: [239, 68, 68],
    description: 'See the details in the transcript panel',
    ringSpeed: 0.0,
    particleCount: 4,
    pulseIntensity: 0.4,
    coreScale: 0.65,
  },
};

export type NavPanel = 'history' | 'memory' | 'settings' | 'preview';
