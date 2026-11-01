import './assistant.css';

/** Presentation only: all assessment facts come from the server. */
export function createScenarioAssistant(host: HTMLElement, onOpen = () => {}) {
  const root = document.createElement('aside');
  root.className = 'scenario-assistant';
  root.hidden = true;
  root.setAttribute('aria-label', 'Реплика персонажа');
  root.innerHTML = `<section class="assistant-bubble" role="dialog" aria-label="Реплика персонажа">
    <button class="assistant-close" type="button" aria-label="Свернуть реплику">×</button>
    <div class="assistant-message" role="status" aria-live="polite" aria-atomic="true"><p></p></div>
    <footer><button class="assistant-next" type="button">Понятно</button></footer>
  </section><button class="assistant-avatar" type="button" aria-label="Открыть реплику персонажа" aria-expanded="false"><img src="/assistant/robot.svg" alt="Офицер" draggable="false"></button>`;
  host.append(root);
  const bubble = root.querySelector<HTMLElement>('.assistant-bubble')!;
  const avatar = root.querySelector<HTMLButtonElement>('.assistant-avatar')!;
  const text = root.querySelector('p')!;
  const next = root.querySelector<HTMLButtonElement>('.assistant-next')!;
  let replies: string[] = [];
  let replyIndex = 0;
  let opened = false;
  let dismissAnimation: Animation | undefined;
  let avatarAnimation: Animation | undefined;
  function dismissAvatar() {
    const distance = window.innerWidth - avatar.getBoundingClientRect().left + 24;
    const animation = avatar.animate([
      { transform: 'translateX(0)', opacity: 1 },
      { transform: `translateX(${distance}px)`, opacity: 0 },
    ], { duration: 280, easing: 'cubic-bezier(.4, 0, 1, 1)', fill: 'forwards' });
    avatarAnimation = animation;
    animation.onfinish = () => {
      if (avatarAnimation !== animation) return;
      root.hidden = true;
      animation.cancel();
      avatarAnimation = undefined;
    };
  }
  function setOpen(value: boolean, animate = true) {
    dismissAnimation?.cancel();
    dismissAnimation = undefined;
    avatarAnimation?.cancel();
    avatarAnimation = undefined;
    opened = value;
    avatar.setAttribute('aria-expanded', String(value));
    bubble.inert = !value;
    if (value) {
      root.hidden = false;
      bubble.hidden = false;
      onOpen();
    } else if (animate && !bubble.hidden && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      const distance = window.innerWidth - bubble.getBoundingClientRect().left + 24;
      const animation = bubble.animate([
        { transform: 'translateX(0)', opacity: 1 },
        { transform: `translateX(${distance}px)`, opacity: 0 },
      ], { duration: 300, easing: 'cubic-bezier(.4, 0, 1, 1)', fill: 'forwards' });
      dismissAnimation = animation;
      animation.onfinish = () => {
        if (dismissAnimation !== animation) return;
        bubble.hidden = true;
        animation.cancel();
        dismissAnimation = undefined;
        dismissAvatar();
      };
    } else { bubble.hidden = true; root.hidden = true; }
  }
  function renderReply() {
    text.textContent = replies[replyIndex];
    text.scrollTop = 0;
    next.textContent = replyIndex < replies.length - 1 ? 'Дальше →' : 'Понятно';
  }
  function show(value: string | string[]) {
    replies = (typeof value === 'string' ? [value] : value).filter(reply => reply.trim());
    if (!replies.length) return;
    replyIndex = 0;
    renderReply();
    root.hidden = false;
    setOpen(true);
  }
  function close() { setOpen(false); avatar.focus(); }
  avatar.onclick = () => setOpen(!opened);
  root.querySelector<HTMLButtonElement>('.assistant-close')!.onclick = close;
  next.onclick = () => {
    if (replyIndex < replies.length - 1) { replyIndex++; renderReply(); }
    else close();
  };
  root.onkeydown = event => { if (event.key === 'Escape') { event.stopPropagation(); close(); } };
  return {
    get isOpen() { return opened; },
    preview() {
      show([
        'Вы правильно пропустили КамАЗ справа.',
        'Перед поворотом снижайте скорость заранее — так будет проще оценить обстановку.',
        'Оцените обстановку перед следующим манёвром и продолжайте движение, когда это безопасно.',
      ]);
    },
    introduction(role: string | null) {
      show(role === 'left-turn'
        ? 'Ваша задача — повернуть налево и остановиться в своей финишной зоне. Оцените обстановку и выберите безопасный момент для манёвра.'
        : 'Ваша задача — проехать прямо и остановиться в своей финишной зоне. Следите за обстановкой на перекрёстке.');
    },
    result(result: string | string[]) { show(result); },
    hide() { setOpen(false, false); root.hidden = true; },
    dispose() { dismissAnimation?.cancel(); avatarAnimation?.cancel(); root.remove(); },
  };
}

/** Offline visual reference; no multiplayer session or generated assessment. */
export function showAssistantPreview(host: HTMLElement) {
  host.innerHTML = `<div class="assistant-preview"><div class="assistant-preview-sky"></div><div class="assistant-preview-road"></div><header><b>АВТОГОРОД</b><span>Перекрёсток · макет помощника</span></header><div class="assistant-preview-controls"><button data-preview="intro">Начало сценария</button><button data-preview="success">Успешный проезд</button><button data-preview="violation">Нарушение</button></div></div>`;
  const assistant = createScenarioAssistant(host);
  host.querySelector<HTMLButtonElement>('[data-preview="intro"]')!.onclick = () => assistant.introduction('left-turn');
  host.querySelector<HTMLButtonElement>('[data-preview="success"]')!.onclick = () => assistant.result('Проезд выполнен правильно');
  host.querySelector<HTMLButtonElement>('[data-preview="violation"]')!.onclick = () => assistant.result('Нарушение: не уступили встречному автомобилю');
  assistant.preview();
  return () => { assistant.dispose(); host.replaceChildren(); };
}
