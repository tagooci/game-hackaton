import { VEHICLE_PAINTS } from '../vehicle/vehiclePaint';
import menuDocument from '../../../frontend/pages/menu.html?raw';
import { mountMenuPreview } from './menuPreview.js';
import authDocument from '../../../frontend/pages/login.html?raw';

export interface Account { playerId: string; name: string }
export interface Profile {
  experience: number;
  level: number;
  levelExperience: number;
  nextLevelExperience: number;
  experienceToNextLevel: number;
  unlockedColors: number[];
  vehicleColor: number;
  vehicleType: 'car' | 'truck' | 'super-sedan';
  isAdmin?: boolean;
  vehicles?: { id: string; unlocked: boolean }[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/v2/${path}`, {
    method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok) throw new ApiError(response.status, data.detail || `HTTP ${response.status}`);
  return data;
}

export function showAuth(host: HTMLElement, onLogin: (account: Account) => Promise<void>, initialError = ''): () => void {
  host.replaceChildren();
  const panel = document.createElement('section');
  const root = panel.attachShadow({ mode: 'open' });
  const documentTemplate = new DOMParser().parseFromString(authDocument, 'text/html');
  const style = document.createElement('style');
  style.textContent = documentTemplate.querySelector('style')!.textContent!.replace(/\bbody\s*\{/g, ':host {') + `
    :host { position: absolute; inset: 0; display: block; overflow: auto; height: 100%; }
    .auth-error { color: #b72b1b; font-size: 14px; line-height: 1.5; margin: 12px 0; }
    .auth-error:empty { display: none; }
    .submit-button:disabled { opacity: .6; cursor: wait; }
  `;
  root.append(style, documentTemplate.querySelector('main')!.cloneNode(true));
  root.querySelectorAll<HTMLImageElement>('img').forEach(image => {
    image.src = image.getAttribute('src')!.replace('./assets/', '/assets/auth/');
  });
  root.querySelectorAll<HTMLFormElement>('form').forEach(form => {
    const submit = form.querySelector<HTMLButtonElement>('.submit-button')!;
    submit.type = 'submit';
    const error = document.createElement('p');
    error.className = 'auth-error';
    error.setAttribute('role', 'alert');
    submit.before(error);
  });
  // The visual template calls this field “Почта”; the API accepts it as username.
  root.querySelector<HTMLInputElement>('#register-email')!.type = 'text';
  host.append(panel);

  const events = new AbortController();
  const options = { signal: events.signal };
  let disposed = false;
  let busy = false;
  const originalTitle = document.title;
  const loginPage = root.querySelector<HTMLElement>('#login-page')!;
  const registerPage = root.querySelector<HTMLElement>('#register-page')!;
  const registerPassword = root.querySelector<HTMLInputElement>('#register-password')!;
  const confirmation = root.querySelector<HTMLInputElement>('#repeat-password')!;

  function setMode(register: boolean): void {
    if (busy) return;
    loginPage.hidden = register;
    registerPage.hidden = !register;
    root.querySelectorAll<HTMLElement>('[role=alert]').forEach(node => { node.textContent = ''; });
    document.title = register ? 'Регистрация — Разъезд' : 'Войти в Разъезд';
  }
  setMode(false);
  root.querySelector<HTMLElement>('#login-form [role=alert]')!.textContent = initialError;

  root.querySelectorAll<HTMLAnchorElement>('.switch-link').forEach(link => {
    link.addEventListener('click', event => {
      event.preventDefault();
      setMode(link.getAttribute('href') === '#register');
    }, options);
  });

  root.querySelectorAll<HTMLButtonElement>('[data-password-toggle]').forEach(button => {
    button.addEventListener('click', () => {
      const input = root.querySelector<HTMLInputElement>(`#${button.dataset.passwordToggle}`)!;
      const visible = input.type === 'password';
      input.type = visible ? 'text' : 'password';
      button.querySelector('img')!.src = `/assets/auth/eye-icons/${visible ? 'eye-off' : 'eye'}.svg`;
      button.setAttribute('aria-label', visible ? 'Скрыть пароль' : 'Показать пароль');
      button.setAttribute('aria-pressed', String(visible));
    }, options);
  });

  function validateConfirmation(): void {
    confirmation.setCustomValidity(registerPassword.value === confirmation.value ? '' : 'Пароли не совпадают');
  }
  registerPassword.addEventListener('input', validateConfirmation, options);
  confirmation.addEventListener('input', validateConfirmation, options);

  root.querySelectorAll<HTMLFormElement>('form').forEach(form => {
    const register = form.id === 'register-form';
    const username = form.querySelector<HTMLInputElement>(register ? '#register-email' : '#login-nickname')!;
    const password = form.querySelector<HTMLInputElement>(register ? '#register-password' : '#login-password')!;
    const name = register ? form.querySelector<HTMLInputElement>('#register-nickname')! : null;
    username.required = password.required = true;
    username.maxLength = 32;
    password.maxLength = 128;
    if (register) {
      username.minLength = 3;
      password.minLength = 8;
      confirmation.required = true;
      confirmation.maxLength = 128;
      name!.required = true;
      name!.maxLength = 24;
      username.autocomplete = 'username';
      name!.setAttribute('autocomplete', 'nickname');
    }
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (busy || disposed) return;
      if (register) validateConfirmation();
      if (!form.reportValidity()) return;
      const errorText = form.querySelector<HTMLElement>('[role=alert]')!;
      const submit = form.querySelector<HTMLButtonElement>('[type=submit]')!;
      busy = true;
      submit.disabled = true;
      errorText.textContent = '';
      try {
        const credentials = { username: username.value.trim(), password: password.value };
        const account = await api<Account>(register ? 'register' : 'login', register
          ? { ...credentials, name: name!.value.trim() }
          : credentials);
        if (!disposed) await onLogin(account);
      } catch (error) {
        if (!disposed) errorText.textContent = error instanceof ApiError
          ? ({ 400: 'Проверьте заполненные поля', 401: 'Неверный ник или пароль', 409: 'Этот логин уже занят' }[error.status] || error.message)
          : 'Сервер недоступен. Попробуйте ещё раз.';
      } finally {
        busy = false;
        if (!disposed) submit.disabled = false;
      }
    }, options);
  });

  return () => {
    disposed = true;
    events.abort();
    panel.remove();
    document.title = originalTitle;
  };
}

export function showGarage(
  host: HTMLElement,
  profile: Profile,
  onStart: (profile: Profile) => Promise<void>,
): () => void {
  host.replaceChildren();
  const panel = document.createElement('section');
  const root = panel.attachShadow({ mode: 'open' });
  const template = new DOMParser().parseFromString(menuDocument, 'text/html');
  const style = document.createElement('style');
  style.textContent = template.querySelector('style')!.textContent!
    .replace(/:root/g, ':host').replace(/\bbody\s*\{/g, ':host {')
    + ':host { position:absolute; inset:0; display:block; overflow:auto; }';
  root.append(style, template.querySelector('main')!.cloneNode(true));
  root.querySelectorAll<HTMLImageElement>('img').forEach(image => {
    image.src = image.getAttribute('src')!.replace('./assets/', '/assets/menu/');
  });
  host.append(panel);
  let disposed = false;
  let adminPingTimer: number | undefined;
  const progress = root.querySelector<HTMLElement>('.progress-panel')!;
  root.querySelector<HTMLElement>('.level-value')!.textContent = String(profile.level);
  const progressBar = root.querySelector<HTMLElement>('.progress-bar')!;
  const progressFill = root.querySelector<HTMLElement>('.progress-fill')!;
  const progressValue = root.querySelector<HTMLElement>('.progress-value')!;
  const progressPercent = profile.level >= 3
    ? 100
    : Math.min(100, profile.levelExperience / profile.nextLevelExperience * 100);
  progressFill.style.width = `${progressPercent}%`;
  progressBar.setAttribute('aria-valuenow', String(Math.round(progressPercent)));
  progressValue.textContent = profile.level >= 3
    ? `${profile.experience} XP · Максимальный уровень`
    : `${profile.experience} XP · ещё ${profile.experienceToNextLevel} XP до уровня ${profile.level + 1}`;
  progress.setAttribute('aria-label', `Уровень ${profile.level}, ${progressValue.textContent}`);
  if (profile.isAdmin) {
    const controls = root.querySelector<HTMLElement>('.controls')!;
    const admin = document.createElement('section');
    admin.className = 'admin-panel';
    admin.innerHTML = `
      <h2>Настройки сервера</h2>
      <fieldset>
        <legend>Погода</legend>
        <label><input type="radio" name="admin-weather" value="clear"> Ясно</label>
        <label><input type="radio" name="admin-weather" value="rain"> Дождь</label>
        <label><input type="radio" name="admin-weather" value="fog"> Туман</label>
        <label><input type="radio" name="admin-weather" value="dark"> Ночь</label>
      </fieldset>
      <fieldset>
        <legend>Режим агента</legend>
        <label><input type="radio" name="admin-agent-style" value="normal"> Обычный</label>
        <label><input type="radio" name="admin-agent-style" value="coach"> Тренер</label>
        <label><input type="radio" name="admin-agent-style" value="aggressive"> Прямой</label>
      </fieldset>
      <div class="admin-pings" aria-live="polite">
        <h3>Пинг игроков</h3>
        <p class="admin-pings-status">Загрузка…</p>
        <ul class="admin-pings-list"></ul>
      </div>
      <p class="admin-status" role="status" aria-live="polite"></p>
    `;
    controls.append(admin);
    style.textContent += `
      .admin-panel { width: 100%; margin-top: 28px; padding: 20px; border: 3px solid var(--ink); border-radius: 18px; background: #f8eee2; color: var(--ink); box-shadow: 4px 4px 0 var(--ink); }
      .admin-panel h2 { margin: 0 0 22px; font-size: 20px; line-height: 1.2; font-weight: 700; }
      .admin-panel fieldset { min-width: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 115px), 1fr)); gap: 10px; margin: 0 0 20px; padding: 0; border: 0; }
      .admin-panel legend { margin-bottom: 10px; padding: 0; font-size: 13px; line-height: 1.4; font-weight: 700; }
      .admin-panel label { min-height: 44px; display: flex; align-items: center; gap: 8px; padding: 10px; border: 2px solid var(--ink); border-radius: 10px; background: #fff9f0; color: var(--ink); font-size: 12px; line-height: 1.3; font-weight: 600; cursor: pointer; transition: background 160ms ease, color 160ms ease, transform 160ms ease, box-shadow 160ms ease; }
      .admin-panel label:hover { background: #f2e4d5; transform: translateY(-2px); }
      .admin-panel label:active { transform: translateY(1px); }
      .admin-panel label:has(input:checked) { background: var(--accent); color: #fff; box-shadow: 2px 2px 0 var(--ink); }
      .admin-panel input { appearance: none; flex: 0 0 16px; width: 16px; height: 16px; margin: 0; border: 2px solid currentColor; border-radius: 50%; background: transparent; cursor: pointer; }
      .admin-panel input:checked { background: #fff; box-shadow: inset 0 0 0 3px var(--accent); }
      .admin-panel label:has(input:focus-visible) { outline: 3px solid var(--ink); outline-offset: 4px; }
      .admin-panel input:focus-visible { outline: none; }
      .admin-status { min-height: 1.4em; margin: 0; color: #555; font-size: 12px; line-height: 1.4; }
      .admin-status.error { color: var(--accent); }
      .admin-pings { margin: 24px 0; padding-top: 20px; border-top: 2px solid #d5c3b2; }
      .admin-pings h3 { margin: 0 0 10px; font-size: 15px; }
      .admin-pings-status { margin: 0 0 8px; color: #555; font-size: 12px; }
      .admin-pings-list { display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }
      .admin-pings-list li { display: flex; justify-content: space-between; gap: 12px; padding: 8px 10px; border-radius: 8px; background: #fff9f0; font-size: 12px; }
      .admin-pings-list strong { font-variant-numeric: tabular-nums; }
      @media (prefers-reduced-motion: reduce) { .admin-panel label { transition: none; } }
    `;
    const weather = admin.querySelectorAll<HTMLInputElement>('input[name="admin-weather"]');
    const agentStyle = admin.querySelectorAll<HTMLInputElement>('input[name="admin-agent-style"]');
    const pingStatus = admin.querySelector<HTMLElement>('.admin-pings-status')!;
    const pingList = admin.querySelector<HTMLUListElement>('.admin-pings-list')!;
    const status = admin.querySelector<HTMLElement>('.admin-status')!;
    const renderPings = (players: { name: string; ping: number | null }[]) => {
      pingList.replaceChildren();
      if (!players.length) {
        pingStatus.textContent = 'Нет подключённых игроков';
        return;
      }
      pingStatus.textContent = '';
      players.forEach(player => {
        const item = document.createElement('li');
        const name = document.createElement('span');
        const ping = document.createElement('strong');
        name.textContent = player.name;
        ping.textContent = player.ping === null ? '—' : `${player.ping} мс`;
        item.append(name, ping);
        pingList.append(item);
      });
    };
    const refreshPings = async (): Promise<void> => {
      try {
        const players = await api<{ name: string; ping: number | null }[]>('admin/players');
        if (!disposed) renderPings(players);
      } catch {
        if (!disposed) pingStatus.textContent = 'Не удалось получить данные';
      }
    };
    void refreshPings();
    adminPingTimer = window.setInterval(refreshPings, 2000);
    void (async (): Promise<void> => {
      try {
        const settings = await api<{ weather: string; agentStyle: string }>('admin/settings');
        if (disposed) return;
        const select = (inputs: NodeListOf<HTMLInputElement>, value: string) => {
          const input = Array.from(inputs).find(item => item.value === value);
          if (input) input.checked = true;
        };
        select(weather, settings.weather);
        select(agentStyle, settings.agentStyle);
      } catch {
        if (!disposed) {
          status.className = 'admin-status error';
          status.textContent = 'Не удалось загрузить настройки';
        }
        return;
      }
      let saving = false;
      const save = async (): Promise<void> => {
        if (saving || disposed) return;
        const selectedWeather = admin.querySelector<HTMLInputElement>('input[name="admin-weather"]:checked');
        const selectedAgentStyle = admin.querySelector<HTMLInputElement>('input[name="admin-agent-style"]:checked');
        if (!selectedWeather || !selectedAgentStyle) return;
        saving = true;
        status.className = 'admin-status';
        status.textContent = 'Сохраняем…';
        try {
          await api('admin/settings', {
            weather: selectedWeather.value,
            agentStyle: selectedAgentStyle.value,
          });
          if (!disposed) status.textContent = 'Настройки сохранены';
        } catch {
          if (!disposed) {
            status.className = 'admin-status error';
            status.textContent = 'Не удалось сохранить настройки';
          }
        } finally {
          saving = false;
        }
      };
      weather.forEach(input => input.addEventListener('change', save));
      agentStyle.forEach(input => input.addEventListener('change', save));
    })();
  }
  const order = [3, 0, 4, 1, 2];
  root.querySelectorAll<HTMLButtonElement>('.color-option').forEach((button, index) => {
    const paint = VEHICLE_PAINTS[order[index]];
    button.dataset.color = paint.color;
    button.style.background = paint.color;
    button.disabled = !profile.unlockedColors.includes(paint.id);
    button.title = paint.label;
    button.setAttribute('aria-label', paint.label);
    if (button.disabled) button.title = `${paint.label} — откроется на 2 уровне`;
    button.replaceChildren();
  });
  const colors = Object.fromEntries(VEHICLE_PAINTS.map(paint => [paint.color, paint.id]));
  const selectedColor = VEHICLE_PAINTS[profile.unlockedColors.includes(profile.vehicleColor)
    ? profile.vehicleColor : 3]?.color ?? VEHICLE_PAINTS[3].color;
  const stopPreview = mountMenuPreview(root, selectedColor,
    profile.vehicleType === 'super-sedan' ? 'sports' : 'sedan',
    profile.vehicles?.some(vehicle => vehicle.id === 'super-sedan' && vehicle.unlocked) ?? false,
    async (color: string, model: string) => {
      const saved = await api<Profile>('profile', {
        vehicleColor: colors[color], vehicleType: model === 'sports' ? 'super-sedan' : 'car',
      });
      await onStart(saved);
    });
  return () => {
    disposed = true;
    if (adminPingTimer !== undefined) window.clearInterval(adminPingTimer);
    stopPreview();
    panel.remove();
  };
}
