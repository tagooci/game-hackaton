import './musicPlayer.css';
import { MUSIC_TRACKS } from './musicPlaylist.js';
const icon = path => `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${path}</svg>`;
const pauseIcon = icon('<path d="M9 6.5v11M15 6.5v11"/>');
const playIcon = icon('<path class="music-player__play" d="M9 6.5 18 12 9 17.5Z"/>');
/** One local audio element per game/client; no playback synchronization.
 * @param {HTMLElement} host
 */
export function createMusicPlayer(host, initialTracks = MUSIC_TRACKS) {
  let tracks = (initialTracks.length ? initialTracks : MUSIC_TRACKS).map(track => ({ ...track }));
  let index = 0, playing = false, wantedPlaying = false, disposed = false;
  let operation = 0;
  let autoStartPending = true;
  const events = new AbortController();
  const options = { signal: events.signal };
  const panel = document.createElement('section');
  panel.className = 'music-player';
  panel.setAttribute('aria-label', 'Музыкальный плеер');
  panel.innerHTML = `<p class="music-player__title" aria-live="polite" aria-atomic="true"></p><div class="music-player__controls">
    <button class="music-player__button" type="button" data-action="previous" aria-label="Предыдущий трек" title="Предыдущий трек">${icon('<path d="m11 6-6 6 6 6M5 12h14"/>')}</button>
    <button class="music-player__button music-player__toggle" type="button" data-action="toggle" aria-label="Включить музыку" title="Включить музыку" aria-pressed="false">${playIcon}</button>
    <button class="music-player__button" type="button" data-action="next" aria-label="Следующий трек" title="Следующий трек">${icon('<path d="m13 6 6 6-6 6M19 12H5"/>')}</button></div>
    <p class="music-player__error" role="status" hidden></p>`;
  const title = panel.querySelector('.music-player__title');
  const toggle = panel.querySelector('[data-action="toggle"]');
  const errorText = panel.querySelector('.music-player__error');
  const audio = document.createElement('audio');
  audio.preload = 'none';
  audio.volume = 0.35;
  audio.hidden = true;
  panel.append(audio);
  host.append(panel);

  const getState = () => ({ index, playing, track: { ...tracks[index] } });
  function render(notify = true) {
    title.textContent = tracks[index].title;
    title.setAttribute('title', tracks[index].title);
    toggle.innerHTML = playing ? pauseIcon : playIcon;
    toggle.setAttribute('aria-label', playing ? 'Пауза' : 'Продолжить воспроизведение');
    toggle.setAttribute('title', playing ? 'Пауза' : 'Продолжить воспроизведение');
    toggle.setAttribute('aria-pressed', String(playing));
    if (notify) panel.dispatchEvent(new CustomEvent('music-player-change', { bubbles: true, detail: getState() }));
  }
  function showError(message = '') {
    errorText.textContent = message;
    errorText.hidden = !message;
  }
  async function play() {
    if (disposed) return;
    autoStartPending = false;
    wantedPlaying = true;
    showError();
    const token = ++operation;
    try {
      await audio.play();
    } catch (error) {
      if (disposed || token !== operation) return;
      wantedPlaying = playing = false;
      showError(error?.name === 'NotAllowedError'
        ? 'Нажмите ▶, чтобы включить музыку'
        : 'Не удалось воспроизвести трек');
      render();
    }
  }
  function pause() {
    autoStartPending = false;
    wantedPlaying = false;
    ++operation;
    audio.pause();
    playing = false;
    render();
  }
  function selectTrack(nextIndex, resume = wantedPlaying) {
    ++operation;
    audio.pause();
    index = (nextIndex + tracks.length) % tracks.length;
    playing = false;
    wantedPlaying = resume;
    showError();
    audio.src = tracks[index].src;
    // preload=none avoids downloading the playlist before the user starts music.
    render();
    if (resume) void play();
  }
  audio.addEventListener('play', () => { if (!disposed) { playing = true; render(); } }, options);
  audio.addEventListener('pause', () => { if (!disposed && playing) { playing = false; render(); } }, options);
  audio.addEventListener('ended', () => selectTrack(index + 1, true), options);
  audio.addEventListener('error', () => {
    if (disposed || !audio.getAttribute('src')) return;
    wantedPlaying = playing = false;
    showError('Не удалось загрузить трек');
    render();
  }, options);
  panel.addEventListener('click', event => {
    const button = event.target instanceof Element ? event.target.closest('[data-action]') : null;
    if (!button || disposed) return;
    autoStartPending = false;
    const action = button.getAttribute('data-action');
    if (action === 'previous') selectTrack(index - 1);
    else if (action === 'next') selectTrack(index + 1);
    else if (wantedPlaying) pause();
    else void play();
  }, options);
  // Browser-safe automatic start: first trusted click/keyboard action in the game.
  const startOnGesture = event => {
    if (!autoStartPending || disposed || !event.isTrusted) return;
    if (event.target instanceof Element && event.target.closest('.music-player, .logout')) return;
    if (event instanceof KeyboardEvent && (event.repeat || event.ctrlKey || event.metaKey || event.altKey)) return;
    void play();
  };
  host.addEventListener('pointerdown', startOnGesture, options);
  host.addEventListener('keydown', startOnGesture, options);
  audio.src = tracks[index].src;
  render(false);
  return {
    getState,
    setTracks(nextTracks) {
      if (disposed || !nextTracks.length) return;
      autoStartPending = false;
      tracks = nextTracks.map(track => ({ title: String(track.title), src: track.src || '' }));
      selectTrack(0, false);
    },
    dispose() {
      disposed = true;
      ++operation;
      events.abort();
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
      panel.remove();
    },
  };
}
