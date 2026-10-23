(() => {
  const sidebar = document.querySelector('#sidebar');
  const scrim = document.querySelector('.scrim');
  const toggle = document.querySelector('.menu-toggle');
  const closeMenu = () => { sidebar?.classList.remove('open'); if (scrim) scrim.hidden = true; toggle?.setAttribute('aria-expanded', 'false'); };
  toggle?.addEventListener('click', () => { sidebar.classList.add('open'); scrim.hidden = false; toggle.setAttribute('aria-expanded', 'true'); });
  scrim?.addEventListener('click', closeMenu);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });

  document.querySelectorAll('[data-open-dialog]').forEach(button => button.addEventListener('click', () => document.getElementById(button.dataset.openDialog)?.showModal()));
  document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog')?.close()));
  document.querySelectorAll('.row-menu').forEach(button => button.addEventListener('click', () => {
    const id = encodeURIComponent(button.dataset.nodeId);
    document.querySelector('#selected-node-name').textContent = button.dataset.nodeName;
    document.querySelector('#rename-name').value = button.dataset.nodeName;
    document.querySelector('#rename-form').action = `/nodes/${id}/rename`;
    document.querySelector('#move-form').action = `/nodes/${id}/move`;
    document.querySelector('#node-dialog').showModal();
  }));
  const search = document.querySelector('#folder-search');
  search?.addEventListener('input', () => {
    let visible = 0;
    document.querySelectorAll('#file-list .file-row').forEach(row => { row.hidden = !row.dataset.name.includes(search.value.toLocaleLowerCase()); if (!row.hidden) visible++; });
    document.querySelector('#search-empty').hidden = !search.value || visible > 0;
  });
  const form = document.querySelector('#upload-form');
  form?.addEventListener('submit', event => {
    if (!window.XMLHttpRequest) return;
    event.preventDefault();
    const status = form.querySelector('.upload-status');
    const progress = form.querySelector('.upload-progress');
    const bar = progress.querySelector('span');
    const button = form.querySelector('[type=submit]');
    button.disabled = true; status.textContent = 'Subiendo…'; progress.hidden = false;
    const xhr = new XMLHttpRequest(); xhr.open('POST', form.action);
    xhr.upload.onprogress = e => { if (e.lengthComputable) bar.style.width = `${Math.round(e.loaded / e.total * 100)}%`; };
    xhr.onload = () => { if (xhr.status >= 200 && xhr.status < 400) location.href = xhr.responseURL || location.href; else { status.textContent = `No se pudo subir el archivo (${xhr.status}). Revisá el nombre, el espacio y los permisos del disco.`; button.disabled = false; } };
    xhr.onerror = () => { status.textContent = 'Se perdió la conexión. Volvé a intentar.'; button.disabled = false; };
    xhr.send(new FormData(form));
  });
})();
