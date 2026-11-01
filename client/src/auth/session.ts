import authDocument from '../../../frontend/pages/login.html?raw';

export interface Account { playerId: string; name: string }
export interface Profile {
  experience: number;
  level: number;
  vehicleColor: number;
  vehicleType: 'car' | 'truck';
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
  panel.className = 'garage-screen';
  panel.innerHTML = `<form class="garage-form">
    <h1>Гараж</h1>
    <p>Уровень <strong data-level></strong> · Опыт <strong data-experience></strong></p>
    <fieldset><legend>Цвет машинки</legend>
      <div class="color-options">${[0, 1, 2, 3, 4].map(color =>
        `<label class="color-${color}"><input type="radio" name="vehicleColor" value="${color}"><span></span></label>`).join('')}</div>
    </fieldset>
    <fieldset><legend>Машинка</legend>
      <label class="vehicle-option"><input type="radio" name="vehicleType" value="car"> Легковая</label>
      <label class="vehicle-option"><input type="radio" name="vehicleType" value="truck"> Грузовая <small>(открывается с 3 уровня)</small></label>
    </fieldset>
    <p class="garage-error" role="alert"></p>
    <button type="submit">Подключиться к карте</button>
  </form>`;
  host.append(panel);
  const form = panel.querySelector('form')!;
  const error = panel.querySelector<HTMLElement>('[role=alert]')!;
  panel.querySelector<HTMLElement>('[data-level]')!.textContent = String(profile.level);
  panel.querySelector<HTMLElement>('[data-experience]')!.textContent = String(profile.experience);
  form.querySelector<HTMLInputElement>(`[name=vehicleColor][value="${profile.vehicleColor}"]`)!.checked = true;
  form.querySelector<HTMLInputElement>(`[name=vehicleType][value="${profile.vehicleType}"]`)!.checked = true;
  form.querySelector<HTMLInputElement>('[value=truck]')!.disabled = profile.level < 3;
  let disposed = false;
  form.onsubmit = async event => {
    event.preventDefault();
    const data = new FormData(form);
    const next: Profile = {
      ...profile,
      vehicleColor: Number(data.get('vehicleColor')),
      vehicleType: data.get('vehicleType') as Profile['vehicleType'],
    };
    const submit = form.querySelector<HTMLButtonElement>('[type=submit]')!;
    submit.disabled = true;
    error.textContent = '';
    try {
      const saved = await api<Profile>('profile', next);
      if (!disposed) await onStart(saved);
    } catch (reason) {
      error.textContent = reason instanceof ApiError ? reason.message : 'Не удалось сохранить выбор';
      submit.disabled = false;
    }
  };
  return () => { disposed = true; panel.remove(); };
}
