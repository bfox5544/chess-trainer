// Move and capture sounds, synthesized with the Web Audio API (no audio
// files to ship or license). A move is a short wooden knock; a capture is a
// heavier knock with a second, sharper click. The on/off choice is kept in
// localStorage; sound starts on (browsers only allow audio after the first
// click or key press anyway).

const KEY = "chessTrainer.sound";
const listeners = new Set();
let context = null;
let noise = null;

function stored() {
  try {
    return localStorage.getItem(KEY) !== "off";
  } catch {
    return true;
  }
}

let enabled = stored();

function audio() {
  if (!context) {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return null;
    context = new Context();
    // A tenth of a second of white noise, reused by every knock.
    noise = context.createBuffer(1, Math.ceil(context.sampleRate * 0.1), context.sampleRate);
    const data = noise.getChannelData(0);
    for (let i = 0; i < data.length; i += 1) data[i] = Math.random() * 2 - 1;
  }
  if (context.state === "suspended") context.resume().catch(() => {});
  return context;
}

/** One knock: filtered noise for the click plus a low sine for the body. */
function knock(ctx, at, { pitch, body, volume, length }) {
  const out = ctx.createGain();
  out.gain.setValueAtTime(volume, at);
  out.gain.exponentialRampToValueAtTime(0.001, at + length);
  out.connect(ctx.destination);

  const click = ctx.createBufferSource();
  click.buffer = noise;
  const band = ctx.createBiquadFilter();
  band.type = "bandpass";
  band.frequency.value = pitch;
  band.Q.value = 1.2;
  click.connect(band).connect(out);
  click.start(at, 0, length);

  const tone = ctx.createOscillator();
  tone.type = "sine";
  tone.frequency.setValueAtTime(body, at);
  tone.frequency.exponentialRampToValueAtTime(body * 0.6, at + length);
  const toneGain = ctx.createGain();
  toneGain.gain.value = 0.6;
  tone.connect(toneGain).connect(out);
  tone.start(at);
  tone.stop(at + length);
}

/** Play the sound for a move: `capture` is true when a piece was taken. */
export function playMoveSound({ capture = false } = {}) {
  if (!enabled) return;
  const ctx = audio();
  if (!ctx || ctx.state === "closed") return;
  const now = ctx.currentTime + 0.005;
  if (capture) {
    knock(ctx, now, { pitch: 1300, body: 150, volume: 0.55, length: 0.09 });
    knock(ctx, now + 0.035, { pitch: 2600, body: 240, volume: 0.35, length: 0.06 });
  } else {
    knock(ctx, now, { pitch: 1800, body: 190, volume: 0.4, length: 0.07 });
  }
}

export const sound = {
  get enabled() {
    return enabled;
  },
  set(on) {
    enabled = on;
    try {
      localStorage.setItem(KEY, on ? "on" : "off");
    } catch {
      /* storage unavailable: the choice lasts for this page load */
    }
    if (on) audio(); // the toggle click is a user gesture: unlock audio now
    listeners.forEach((listener) => listener(on));
  },
  toggle() {
    this.set(!enabled);
  },
  subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

// Browsers start audio suspended until the user interacts with the page.
// Unlock it on the first click or key press, so the move that follows (or
// the engine's reply a moment later) is heard.
function unlock() {
  if (enabled) audio();
  window.removeEventListener("pointerdown", unlock, true);
  window.removeEventListener("keydown", unlock, true);
}
window.addEventListener("pointerdown", unlock, true);
window.addEventListener("keydown", unlock, true);
