import { VEHICLE_PAINTS } from '../vehicle/vehiclePaint';
import menuDocument from '../../../frontend/pages/menu.html?raw';
import { mountMenuPreview } from './menuPreview.js';
import authDocument from '../../../frontend/pages/login.html?raw';

export interface Account { playerId: string; name: string }
export interface Profile {
  experience: number;
  level: number;
  vehicleColor: number;
  vehicleType: 'car' | 'truck' | 'super-sedan';
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
  const order = [3, 0, 4, 1, 2];
  root.querySelectorAll<HTMLButtonElement>('.color-option').forEach((button, index) => {
    const paint = VEHICLE_PAINTS[order[index]];
    button.dataset.color = paint.color;
    button.style.background = paint.color;
    button.disabled = false;
    button.title = paint.label;
    button.setAttribute('aria-label', paint.label);
    button.replaceChildren();
  });
  const colors = Object.fromEntries(VEHICLE_PAINTS.map(paint => [paint.color, paint.id]));
  const selectedColor = VEHICLE_PAINTS[profile.vehicleColor]?.color ?? VEHICLE_PAINTS[3].color;
  const stopPreview = mountMenuPreview(root, selectedColor,
    profile.vehicleType === 'super-sedan' ? 'sports' : 'sedan',
    profile.vehicles?.some(vehicle => vehicle.id === 'super-sedan' && vehicle.unlocked) ?? false,
    async (color: string, model: string) => {
      if (model === 'sports') throw new Error('Спортивная машина пока не подключена на сервере');
      const saved = await api<Profile>('profile', {
        vehicleColor: colors[color], vehicleType: model === 'sports' ? 'super-sedan' : 'car',
      });
      await onStart(saved);
    });
  return () => { stopPreview(); panel.remove(); };
}
