const AUDIO_DIRECTION = /\[(?:calm|warmly|curious|crying|mischievously|whispers|shouts|laughs|clears throat|sighs|happy|sad|angry|excited|tired|quietly)\][ \t]*(?::[ \t]*)?/gi

export function cleanAgentText(text: string): string {
  return text.replace(AUDIO_DIRECTION, ' ').replace(/[ \t]{2,}/g, ' ').trim()
}
