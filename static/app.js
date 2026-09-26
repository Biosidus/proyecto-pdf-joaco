const ALLOWED = [".cbr", ".cbz", ".rar", ".zip", ".pdf"];
const POLL_MS = 600;

const $ = (id) => document.getElementById(id);

const ui = {
  drop: $("drop"),
  file: $("file"),
  stages: {
    drop: $("stage-drop"),
    work: $("stage-work"),
    error: $("stage-error"),
    done: $("stage-done"),
  },
  workFile: $("work-file"),
  phase: $("work-phase"),
  count: $("work-count"),
  meter: $("meter"),
  meterFill: $("meter-fill"),
  errorBody: $("error-body"),
  retry: $("retry"),
  doneTitle: $("done-title"),
  doneBody: $("done-body"),
  flipHint: $("flip-hint"),
  download: $("download"),
  flip: $("flip"),
  again: $("again"),
  report: $("report"),
  reportTitle: $("report-title"),
  gallery: $("gallery"),
  reportEmpty: $("report-empty"),
  live: $("live"),
  views: Array.from(document.querySelectorAll(".seg")),
};

const state = { job: null, view: "changed", polling: null, maxUploadMb: null };

function showStage(name) {
  for (const [key, node] of Object.entries(ui.stages)) node.hidden = key !== name;
}

function announce(text) {
  ui.live.textContent = text;
}

function setBusy(busy) {
  ui.file.disabled = busy;
  ui.drop.setAttribute("aria-disabled", busy ? "true" : "false");
}

function setProgress(ratio, label) {
  const pct = Math.max(0, Math.min(1, ratio)) * 100;
  ui.meterFill.style.width = pct + "%";
  ui.meter.setAttribute("aria-valuenow", Math.round(pct));
  if (label) announce(label);
}

function formatNumber(value) {
  return new Intl.NumberFormat("es-AR").format(value);
}

function formatSize(bytes) {
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

/* ---------- Arranque ---------- */

function bindEvents() {
  ui.file.addEventListener("change", () => {
    if (ui.file.files && ui.file.files[0]) start(ui.file.files[0]);
  });

  ["dragenter", "dragover"].forEach((type) =>
    ui.drop.addEventListener(type, (event) => {
      event.preventDefault();
      if (ui.file.disabled) return;
      ui.drop.classList.add("is-over");
    })
  );

  ["dragleave", "dragend", "drop"].forEach((type) =>
    ui.drop.addEventListener(type, (event) => {
      event.preventDefault();
      ui.drop.classList.remove("is-over");
      if (type !== "drop" || ui.file.disabled) return;
      const file = event.dataTransfer && event.dataTransfer.files[0];
      if (file) start(file);
    })
  );

  ui.retry.addEventListener("click", reset);
  ui.again.addEventListener("click", reset);
  ui.flip.addEventListener("click", flip);

  ui.views.forEach((button) =>
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      ui.views.forEach((other) => other.classList.toggle("is-on", other === button));
      renderGallery();
    })
  );
}

function reset() {
  if (state.polling) clearTimeout(state.polling);
  state.polling = null;
  state.job = null;
  state.view = "changed";
  ui.views.forEach((button) => button.classList.toggle("is-on", button.dataset.view === "changed"));
  ui.file.value = "";
  ui.gallery.replaceChildren();
  ui.report.hidden = true;
  ui.flip.disabled = false;
  setBusy(false);
  setProgress(0);
  showStage("drop");
  ui.file.focus();
}

async function start(file) {
  const name = file.name.toLowerCase();
  const suffix = name.slice(name.lastIndexOf("."));
  if (!ALLOWED.includes(suffix)) {
    showError(`«${file.name}» no es un formato soportado. Se aceptan .cbr, .cbz, .rar, .zip y .pdf.`);
    return;
  }

  if (state.maxUploadMb && file.size > state.maxUploadMb * 1024 * 1024) {
    showError(
      `«${file.name}» pesa ${formatSize(file.size)} y el límite es ${state.maxUploadMb} MB. ` +
        "Se puede subir el límite con MAX_UPLOAD_MB en el .env."
    );
    return;
  }

  setBusy(true);
  ui.workFile.textContent = `${file.name} · ${formatSize(file.size)}`;
  ui.phase.textContent = "Subiendo el archivo";
  ui.count.textContent = "";
  ui.report.hidden = true;
  setProgress(0, "Subiendo el archivo");
  showStage("work");

  try {
    state.job = await upload(file);
    ui.workFile.textContent = state.job.archivo;
    schedulePoll();
  } catch (error) {
    showError(error.message);
  }
}

function upload(file) {
  return new Promise((resolve, reject) => {
    const body = new FormData();
    body.append("file", file, file.name);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/jobs");
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        setProgress(event.loaded / event.total, "Subiendo el archivo");
        ui.count.textContent = `${Math.round((event.loaded / event.total) * 100)} %`;
      }
    });
    xhr.addEventListener("load", () => {
      let payload = {};
      try {
        payload = JSON.parse(xhr.responseText);
      } catch {
        payload = {};
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(payload);
      else reject(new Error(payload.detail || `El servidor respondió ${xhr.status}.`));
    });
    xhr.addEventListener("error", () =>
      reject(new Error("No hay conexión con el servidor local. ¿Sigue corriendo python app.py?"))
    );
    xhr.send(body);
  });
}

function schedulePoll() {
  state.polling = setTimeout(poll, POLL_MS);
}

async function poll() {
  let job;
  try {
    const res = await fetch(`/api/jobs/${state.job.id}`, { cache: "no-store" });
    if (res.status === 404) throw new Error("El trabajo se perdió del lado del servidor.");
    job = await res.json();
  } catch (error) {
    showError(error.message);
    return;
  }

  state.job = job;
  ui.phase.textContent = job.fase;
  if (job.total) {
    setProgress(job.progreso, `${job.fase}, ${job.hechas} de ${job.total}`);
    ui.count.textContent = `${formatNumber(job.hechas)} / ${formatNumber(job.total)}`;
  } else {
    setProgress(0, job.fase);
    ui.count.textContent = "";
  }

  if (job.estado === "error") {
    showError(job.error || job.mensaje);
    return;
  }

  if (job.estado === "done") {
    renderResult();
    return;
  }

  schedulePoll();
}

function flip() {
  if (!state.job || ui.flip.disabled) return;
  ui.flip.disabled = true;
  ui.phase.textContent = "Dando vuelta las dobles";
  ui.count.textContent = "";
  setProgress(0, "Dando vuelta las dobles");
  showStage("work");

  fetch(`/api/jobs/${state.job.id}/flip`, { method: "POST" })
    .then((res) => {
      if (!res.ok) throw new Error("No se pudo dar vuelta las páginas.");
      schedulePoll();
    })
    .catch((error) => showError(error.message));
}

/* ---------- Resultado ---------- */

function renderResult() {
  const job = state.job;
  const resumen = job.resumen || {};
  const giradas = resumen.giradas || 0;
  const dudosas = job.dudosas || 0;

  const partes = [`${formatNumber(resumen.total || job.paginas)} páginas.`];
  if (giradas) {
    partes.push(`Enderecé ${formatNumber(giradas)} dobles, que quedaron en horizontal.`);
  } else {
    partes.push("No encontré dobles guardadas acostadas: no hubo que enderezar nada.");
  }
  if (dudosas) {
    partes.push(
      `${formatNumber(dudosas)} quedaron en duda y las dejé como estaban; están marcadas abajo.`
    );
  }

  ui.doneTitle.textContent = giradas ? "PDF listo" : "PDF listo, sin cambios";
  ui.doneBody.textContent = partes.join(" ");
  ui.flipHint.hidden = giradas === 0;
  ui.flip.hidden = giradas === 0;
  ui.flip.disabled = false;

  const version = `v=${job.giro_dobles}-${giradas}`;
  ui.download.href = `${job.descarga}?${version}`;

  state.view = giradas ? "changed" : "all";
  ui.views.forEach((button) => button.classList.toggle("is-on", button.dataset.view === state.view));

  renderGallery();
  ui.report.hidden = false;
  showStage("done");
  setBusy(false);
  announce(ui.doneBody.textContent);
  ui.download.focus();
}

function renderGallery() {
  const job = state.job;
  const detalle = job.detalle || [];
  const mostradas = state.view === "changed" ? detalle.filter((item) => item.giro !== 0) : detalle;

  ui.reportTitle.textContent = state.view === "changed"
    ? `Páginas enderezadas (${mostradas.length})`
    : `Todas las páginas (${mostradas.length})`;

  ui.gallery.replaceChildren(...mostradas.map(buildShot));

  ui.reportEmpty.hidden = mostradas.length > 0;
  if (!mostradas.length) {
    ui.reportEmpty.textContent = "Este tomo no tiene páginas dobles guardadas acostadas.";
  }
}

function buildShot(item) {
  const shot = document.createElement("figure");
  shot.className = "shot" + (item.giro ? " shot--changed" : "");

  const frame = document.createElement("div");
  frame.className = "shot__frame";
  const img = document.createElement("img");
  img.loading = "lazy";
  img.decoding = "async";
  img.alt = `Página ${item.numero}`;
  img.src = `${state.job.miniaturas}/${item.numero}?v=${state.job.giro_dobles}`;
  frame.append(img);

  const label = document.createElement("figcaption");
  label.className = "shot__label";
  const numero = document.createElement("span");
  numero.className = "shot__num";
  numero.textContent = `pág. ${item.numero}`;
  const tag = document.createElement("span");
  tag.className = item.giro ? "shot__tag" : "shot__tag shot__tag--plain";
  tag.textContent = item.giro ? `girada ${item.giro}°` : "sin cambios";
  label.append(numero, tag);

  shot.title = item.motivo || "";
  shot.append(frame, label);
  return shot;
}

function showError(message) {
  ui.errorBody.textContent = message;
  ui.report.hidden = true;
  showStage("error");
  setBusy(false);
  ui.flip.disabled = false;
  announce("Error: " + message);
  ui.retry.focus();
}

async function loadLimits() {
  try {
    const res = await fetch("/api/health", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    if (data.max_upload_mb) state.maxUploadMb = data.max_upload_mb;
  } catch {
    /* si no responde, el límite lo aplica igual el servidor al subir */
  }
}

bindEvents();
loadLimits();
