# OnClick AI — Voice-first PC agent for Indian languages
**Great Indian AI Internship Challenge 2026 · Rahul S R (MCA AI & ML, JAIN University)**

## Problem
Most PC automation tools expect English typing. Millions of Indian users think and speak in Kannada, Hindi or Hinglish, and many aren't comfortable typing commands at all.

## Solution
OnClick AI is a Windows desktop agent. You speak a task in your own language, and it carries it out on your PC (open apps, manage files, change settings, multi-step tasks), then tells you aloud what it did, in the same language.

Example: say "ನೋಟ್‌ಪ್ಯಾಡ್ ತೆರೆಯಿರಿ" or "Notepad open karo", and Notepad opens. OnClick AI then confirms aloud.

## Gnani models used
| Model | Role |
|---|---|
| **Prisma v2.5 (STT)** — `api.vachana.ai/stt/v3` | Turns the user's voice into text in Kannada, Hindi, Hinglish, Tamil, Telugu and English, with word boosting for app names |
| **Timbre v2.5 (TTS)** — `api.vachana.ai/api/v1/tts/inference` | Speaks replies in a native voice for each language (Kannada: Saanvi and Kavin; Hinglish: Poorvi) |

## How it works
1. The mic captures audio, and voice activity detection with noise gating trims silence.
2. **Prisma** transcribes the speech in the language the user picked.
3. The OnClick planner (an LLM agent) turns the request into steps and runs them on Windows.
4. **Timbre** speaks the result. Long replies are shortened so they sound natural.
5. Retries, clear error messages and a settings screen for the API key make it reliable.

## Results (live tests, 26 Oct 2026)
- Kannada round trip: Timbre spoke the command and Prisma transcribed it back exactly, in about 1.06 s.
- Hinglish: transcribed in about 0.53 s.
- 15 of 15 automated tests pass (`tools/eval_voice.py` measures accuracy and latency).

## Why it matters
It makes computers usable by voice for people who prefer Indian languages, and that is the "Bharat-first" AI Gnani builds for.

## Code
https://github.com/Rahulrachu/OnClick-AI-Gnani · Voice layer in `onclick/voice/` · Demo in `demo/`.
