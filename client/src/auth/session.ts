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
  panel.className = 'auth-screen';
  panel.innerHTML = `<form class="auth-form">
    <h1>Учебный автогород</h1>
    <div class="auth-tabs"><button type="button" data-mode="login">Вход</button><button type="button" data-mode="register">Регистрация</button></div>
    <label>Логин<input name="username" autocomplete="username" minlength="3" maxlength="32" required></label>
    <label>Пароль<input name="password" type="password" autocomplete="current-password" minlength="8" maxlength="128" required></label>
    <label data-register hidden>Повторите пароль<input name="confirmation" type="password" autocomplete="new-password"></label>
    <label data-register hidden>Имя игрока<input name="name" maxlength="24" autocomplete="nickname"></label>
    <p role="alert"></p><button type="submit">Войти</button>
  </form>`;
  host.append(panel);
  const form = panel.querySelector('form')!;
  const submit = form.querySelector<HTMLButtonElement>('[type=submit]')!;
  const errorText = form.querySelector('[role=alert]')!;
  errorText.textContent = initialError;
  let mode = 'login';
  let disposed = false;
  form.querySelectorAll<HTMLButtonElement>('[data-mode]').forEach(button => {
    button.onclick = () => {
      mode = button.dataset.mode!;
      errorText.textContent = '';
      submit.textContent = mode === 'login' ? 'Войти' : 'Создать аккаунт';
      form.querySelectorAll<HTMLElement>('[data-register]').forEach(label => {
        label.hidden = mode !== 'register';
        label.querySelector('input')!.required = mode === 'register';
      });
      form.querySelector<HTMLInputElement>('[name=password]')!.autocomplete = mode === 'login' ? 'current-password' : 'new-password';
    };
  });
  form.onsubmit = async event => {
    event.preventDefault();
    const fields = new FormData(form);
    if (mode === 'register' && fields.get('password') !== fields.get('confirmation')) {
      errorText.textContent = 'Пароли не совпадают';
      return;
    }

    submit.disabled = true;
    errorText.textContent = '';
    try {
      const account = await api<Account>(mode, { username: fields.get('username'), password: fields.get('password'), name: fields.get('name') });
      if (!disposed) await onLogin(account);
    } catch (error) {
      if (!disposed) errorText.textContent = error instanceof ApiError
        ? ({ 400: 'Проверьте заполненные поля', 401: 'Неверный логин или пароль', 409: 'Этот логин уже занят' }[error.status] || error.message)
        : 'Сервер недоступен. Попробуйте ещё раз.';
    } finally { submit.disabled = false; }
  };
  return () => { disposed = true; panel.remove(); };
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
