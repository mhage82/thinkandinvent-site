"use strict";
(() => {
  const assetBase = new URL('.', document.currentScript.src);
  const $ = id => document.getElementById(id);
  let study, dataset, group, session, index = 0, imageReady = false, viewStarted = 0;
  const apiUrl = new URL('../api/annotation', assetBase);
  const localPreview = ['localhost', '127.0.0.1'].includes(location.hostname);
  let onlineReady = false, offlinePreview = false, availabilityBusy = false, submitting = false;
  let groupStates = {}, accessCode = '';
  const completed = id => groupStates[id]?.state === 'completed';
  const now = () => new Date().toISOString();
  const choices = name => [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(el => el.value);
  const imageId = () => group.image_ids[index];
  const keyFor = (annotator, groupId) => `image-annotation:${dataset.dataset_id}:${groupId}:${annotator}`;
  const activeKey = () => keyFor(session.annotator_id, group.id);
  const isComplete = row => row?.status === "annotated";

  function textElement(tag, text, className) {
    const el = document.createElement(tag);
    el.textContent = text;
    if (className) el.className = className;
    return el;
  }

  function showGuide() {
    $("label-guide").replaceChildren();
    $("label-options").replaceChildren();
    for (const label of study.labels) {
      const card = textElement("article", "", "guide-card");
      card.append(textElement("h3", label.name), textElement("p", label.description), textElement("p", `Illustrative example: ${label.example}`));
      $("label-guide").append(card);
      addChoice($("label-options"), "checkbox", "artifact", label);
    }
    $("example-gallery").replaceChildren();
    for (const example of study.examples || []) {
      const figure = document.createElement("figure");
      const image = document.createElement("img");
      image.src = new URL(example.src, assetBase).href;
      image.alt = example.explanation;
      figure.append(image, textElement("figcaption", example.explanation));
      $("example-gallery").append(figure);
    }
    $("contact").textContent = study.contact ? `Questions or return of results: ${study.contact}` : "";
    $("contact").hidden = !study.contact;
    $("return-instructions").textContent = "Click Submit annotations after finishing the group. Wait for confirmation that your results were received. A downloaded backup does not submit your answers.";
  }

  function addChoice(parent, type, name, option) {
    const label = textElement("label", "", "choice");
    const input = document.createElement("input");
    Object.assign(input, {type, name, value: option.id});
    const body = textElement("span", option.name);
    label.title = option.description;
    input.setAttribute("aria-description", option.description);
    label.append(input, body);
    parent.append(label);
  }

  function persist() {
    if (!session) return;
    session.current_index = index;
    session.updated_at = now();
    try {
      localStorage.setItem(activeKey(), JSON.stringify(session));
      $("storage-status").textContent = "Selections saved in this browser. Submit annotations sends the completed group.";
    } catch {
      $("storage-status").textContent = "Browser storage is unavailable or full. Your work is only in this tab; download results before leaving.";
    }
  }

  function saveSelections() {
    if (!session || !group || completed(group.id)) return;
    const id = imageId(), previous = session.annotations[id];
    const selected = choices("artifact");
    const values = {
      labels: selected.filter(x => x !== "none" && x !== "uncertain"),
      artifact_judgment: selected.includes("none") ? "none" : selected.includes("uncertain") ? "uncertain" : selected.length ? "present" : "",
    };
    if (!previous && !selected.length) return;
    const changed = !previous || Object.keys(values).some(k => JSON.stringify(previous[k]) !== JSON.stringify(values[k]));
    const status = values.artifact_judgment ? "annotated" : "draft";
    const {confidence, notes, usability, ...retained} = previous || {};
    session.annotations[id] = {
      ...retained, ...values, image_id: id, status,
      started_at: previous?.started_at || now(),
      updated_at: changed || previous?.status !== status ? now() : previous.updated_at,
      active_seconds: (previous?.active_seconds || 0) + Math.min(300, Math.max(0, (performance.now() - viewStarted) / 1000)),
    };
    viewStarted = performance.now();
  }

  function progress() {
    const annotated = group.image_ids.filter(id => isComplete(session.annotations[id])).length;
    $("progress").max = group.image_ids.length;
    $("progress").value = annotated;
    $("progress-text").textContent = `${annotated} labeled · ${group.image_ids.length - annotated} unfinished`;
    $("completion-heading").textContent = annotated === group.image_ids.length ? "All images labeled — submit your annotations" : "Submit when every image is labeled";
    if (completed(group.id)) $("completion-heading").textContent = session.submission_receipt ? "Submitted successfully" : "This group has been completed";
    updateControls();
    $("jump").replaceChildren(...group.image_ids.map((id, n) => new Option(`${n + 1}${isComplete(session.annotations[id]) ? " ✓" : ""}`, String(n), false, n === index)));
  }

  function render() {
    const id = imageId(), row = session.annotations[id];
    $("annotation-form").reset();
    for (const input of document.querySelectorAll('input[name="artifact"]')) input.checked = row?.labels?.includes(input.value) || row?.artifact_judgment === input.value;
    $("form-error").textContent = "";
    $("image-heading").textContent = `Image ${index + 1} of ${group.image_ids.length}`;
    $("previous").disabled = index === 0;
    $("next").disabled = index === group.image_ids.length - 1;
    imageReady = false;
    $("zoom").disabled = true;
    for (const field of $("annotation-form").querySelectorAll("fieldset")) field.disabled = true;
    $("image-status").textContent = "Loading image…";
    const photo = new Image();
    photo.id = "photo";
    photo.alt = `Image ${index + 1} to label`;
    photo.onload = () => {
      if ($( "photo") !== photo) return;
      imageReady = true;
      $("zoom").disabled = false;
      for (const field of $("annotation-form").querySelectorAll("fieldset")) field.disabled = submitting || completed(group.id);
      $("image-status").textContent = "";
    };
    photo.onerror = () => {
      if ($("photo") !== photo) return;
      $("image-status").textContent = "This image could not load. Refresh the page or move to another image with Next.";
    };
    $("photo").replaceWith(photo);
    photo.src = new URL(dataset.images[id].src, assetBase).href;
    viewStarted = performance.now();
    progress();
    persist();
  }

  function navigate(next) {
    saveSelections(); persist();
    index = Math.max(0, Math.min(group.image_ids.length - 1, next));
    render();
    $("image-heading").focus({preventScroll: true});
  }

  function validateSession(value) {
    if (value.schema_version !== 1 || value.dataset_id !== dataset.dataset_id || value.guidelines_version !== study.guidelines_version) throw Error("These results belong to a different dataset or guidelines version.");
    const targetGroup = dataset.groups.find(x => x.id === value.group_id);
    if (!targetGroup?.image_ids.length || typeof value.annotator_id !== "string" || !value.annotator_id.trim() || value.annotator_id.length > 64 || /[\u0000-\u001f\u007f]/.test(value.annotator_id)) throw Error("Invalid or empty group, or invalid annotator code.");
    if (!value.annotations || Array.isArray(value.annotations) || typeof value.annotations !== "object") throw Error("Invalid annotations.");
    for (const [id, row] of Object.entries(value.annotations)) {
      if (!targetGroup.image_ids.includes(id) || row.image_id !== id || !["draft", "annotated"].includes(row.status)) throw Error("Results contain an invalid image or status.");
      if (!Array.isArray(row.labels) || new Set(row.labels).size !== row.labels.length || row.labels.some(x => !study.labels.some(l => l.id === x))) throw Error("Results contain an unknown or duplicate label.");
      if (!["", "none", "uncertain", "present"].includes(row.artifact_judgment) || (row.artifact_judgment === "present") !== (row.labels.length > 0)) throw Error("Artifact choices are inconsistent.");
      if (row.status === "annotated" && (!row.artifact_judgment)) throw Error("A completed annotation is missing answers.");
      if (!Number.isFinite(row.active_seconds) || row.active_seconds < 0) throw Error("Invalid timing data.");
    }
    return value;
  }

  function begin(annotator, groupId, restored) {
    group = dataset.groups.find(x => x.id === groupId);
    if (!group?.image_ids.length) { $("loading").textContent = "This group has no images yet. Choose a populated group."; return; }
    session = restored || {schema_version: 1, dataset_id: dataset.dataset_id, guidelines_version: study.guidelines_version, annotator_id: annotator, group_id: groupId, started_at: now(), annotations: {}};
    session.submission_id ||= crypto.randomUUID();
    index = Math.max(0, Math.min(group.image_ids.length - 1, Number(session.current_index) || 0));
    $("setup").hidden = true;
    $("workspace").hidden = false;
    document.body.classList.add("annotating");
    $("guide-content").append($("guidelines"));
    $("guidelines").open = true;
    // Only artifact selections are collected by this study version.
    for (const row of Object.values(session.annotations)) {
      delete row.confidence; delete row.notes; delete row.usability;
      row.status = row.artifact_judgment ? "annotated" : "draft";
    }
    window.scrollTo(0, 0);
    $("group-heading").textContent = `${group.name} · ${annotator}`;
    render();
  }

  $("start-form").addEventListener("submit", async event => {
    event.preventDefault();
    accessCode = $("access-code").value;
    const annotator = $("annotator").value.trim(), groupId = $("group").value;
    if (!await refreshAvailability()) return;
    if (!annotator || completed(groupId)) { $("loading").textContent = 'Choose an available group and enter your name or code.'; return; }
    let saved, raw;
    try { raw = localStorage.getItem(keyFor(annotator, groupId)); }
    catch { /* Storage may be blocked: allow annotation with downloadable backups. */ }
    try { if (raw) saved = validateSession(JSON.parse(raw)); }
    catch (error) { $("loading").textContent = `Saved progress could not be read: ${error.message}. Export a backup or use a new annotator code; existing saved data has not been replaced.`; return; }
    begin(annotator, groupId, saved);
  });

  $("annotation-form").addEventListener("input", event => {
    $("form-error").textContent = "";
    if (event.target.name === "artifact" && event.target.checked) {
      const special = ["none", "uncertain"].includes(event.target.value);
      for (const input of document.querySelectorAll('input[name="artifact"]')) if (input !== event.target && (special || ["none", "uncertain"].includes(input.value))) input.checked = false;
    }
    saveSelections(); persist(); progress();
  });
  $("annotation-form").addEventListener("submit", event => event.preventDefault());
  $("previous").onclick = () => navigate(index - 1);
  $("next").onclick = () => navigate(index + 1);
  $("jump").onchange = () => navigate(Number($("jump").value));
  $("first-pending").onclick = () => { const pending = group.image_ids.findIndex(id => !isComplete(session.annotations[id])); if (pending >= 0) navigate(pending); else $("export-status").textContent = "All images are labeled. Click Submit annotations to send them."; };
  $("change-group").onclick = () => { saveSelections(); persist(); session = null; group = null; $("workspace").hidden = true; $("setup").hidden = false; document.body.classList.remove("annotating"); $("storage-status").before($("guidelines")); };
  $("zoom").onclick = () => { if (imageReady) { $("zoom-photo").src = $("photo").src; $("image-dialog").showModal(); } };
  $("show-guide").onclick = () => $("guide-dialog").showModal();
  $("close-guide").onclick = () => $("guide-dialog").close();
  $("close-zoom").onclick = () => $("image-dialog").close();

  function download(format) {
    saveSelections(); persist(); progress();
    const withFilename = (id, row) => ({...row, filename: group.filenames?.[id] || ""});
    const records = group.image_ids.map(id => withFilename(id, session.annotations[id] || {image_id: id, status: "pending", labels: []}));
    let body, type;
    if (format === "json") {
      const annotations = Object.fromEntries(Object.entries(session.annotations).map(([id, row]) => [id, withFilename(id, row)]));
      body = JSON.stringify({...session, annotations, exported_at: now()}, null, 2); type = "application/json";
    }
    else {
      const fields = ["dataset_id", "guidelines_version", "annotator_id", "group_id", "image_id", "filename", "status", "labels", "artifact_judgment", "active_seconds", "updated_at"];
      const cell = value => { let text = String(value ?? ""); if (/^[=+@\-\t\r\n]/.test(text)) text = "'" + text; return '"' + text.replaceAll('"', '""') + '"'; };
      body = fields.join(",") + "\r\n" + records.map(row => fields.map(field => cell(field === "labels" ? row.labels.join("|") : ["dataset_id", "guidelines_version", "annotator_id", "group_id"].includes(field) ? session[field] : row[field])).join(",")).join("\r\n"); type = "text/csv;charset=utf-8";
    }
    const url = URL.createObjectURL(new Blob([body], {type}));
    const a = document.createElement("a"); a.href = url; a.download = `${session.annotator_id}_${group.id}_${dataset.dataset_id}.${format}`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    $("export-status").textContent = session.submission_receipt ? "Backup downloaded. This group has already been submitted." : "Backup downloaded. Click Submit annotations when the group is finished.";
  }
  function updateControls() {
    if (!session || !group) return;
    const locked = submitting || completed(group.id);
    for (const field of $("annotation-form").querySelectorAll("fieldset")) field.disabled = !imageReady || locked;
    $("submit-annotations").disabled = !onlineReady || locked;
    $("submit-annotations").textContent = submitting ? "Submitting…" : completed(group.id) ? "Completed" : "Submit annotations";
    $("previous").disabled = submitting || index === 0;
    $("next").disabled = submitting || index === group.image_ids.length - 1;
    $("jump").disabled = submitting;
    $("change-group").disabled = submitting;
  }

  async function apiRequest(method = 'GET', payload) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45000);
    try {
      const response = await fetch(apiUrl, {
        method, cache: 'no-store', signal: controller.signal,
        ...(payload ? {headers: {'Content-Type': 'application/json', 'X-Annotation-Code': accessCode}, body: JSON.stringify(payload)} : {}),
      });
      let body;
      try { body = await response.json(); } catch { body = {}; }
      if (!response.ok) {
        const error = new Error(body.error || 'Online submission is temporarily unavailable. Please retry.');
        error.code = body.code || 'network';
        throw error;
      }
      return body;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('The request timed out. Your answers remain in this browser. Retry submission to confirm whether they were received.');
      throw error;
    } finally { clearTimeout(timeout); }
  }

  function renderGroupOptions() {
    const selected = $("group").value;
    $("group").replaceChildren();
    const list = document.createElement('ul');
    list.className = 'group-status-list';
    for (const entry of dataset.groups) {
      const done = completed(entry.id);
      const option = new Option(`${entry.name} (${entry.image_ids.length} images)${done ? ' — Completed' : ''}`, entry.id);
      option.disabled = done || !entry.image_ids.length;
      $("group").add(option);
      const item = document.createElement('li');
      item.className = done ? 'completed' : '';
      item.append(textElement(done ? 's' : 'span', entry.name), textElement('small', done ? 'Completed' : entry.image_ids.length ? 'Available' : 'Empty'));
      list.append(item);
    }
    $("group-availability").replaceChildren(list);
    const available = dataset.groups.filter(g => g.image_ids.length && !completed(g.id));
    const requested = new URLSearchParams(location.search).get('group');
    $("group").value = available.some(g => g.id === selected) ? selected : available.some(g => g.id === requested) ? requested : available[0]?.id || '';
    $("start-form").hidden = !available.length;
    $("loading").textContent = available.length ? `${available.length} groups available. Choose one to annotate.` : dataset.groups.some(g => g.image_ids.length) ? 'All groups have been completed. Thank you!' : 'All image groups are empty. Add images and refresh the image list.';
  }

  async function refreshAvailability() {
    if (availabilityBusy) return onlineReady || offlinePreview;
    availabilityBusy = true;
    try {
      const result = await apiRequest();
      if (result.dataset_id !== dataset.dataset_id) throw new Error('The website image list has changed. Download a backup and refresh the page.');
      if (!result.groups || dataset.groups.some(g => !['available', 'completed'].includes(result.groups[g.id]?.state))) throw new Error('Group availability could not be verified. Please retry.');
      saveSelections();
      groupStates = result.groups;
      onlineReady = true; offlinePreview = false;
      $("access-code-field").hidden = !result.requires_access_code;
      $("access-code").required = !!result.requires_access_code;
      $("service-status").textContent = 'Completed groups are closed. Submit annotations sends your results directly to the organizer.';
      renderGroupOptions();
      if (group && completed(group.id)) {
        $("export-status").textContent = session.submission_receipt ? 'Your annotations have been submitted successfully. Thank you!' : 'This group has already been submitted. You can download a backup of your local answers.';
        progress();
      }
      return true;
    } catch (error) {
      onlineReady = false;
      offlinePreview = localPreview && error.code === 'not_configured';
      if (offlinePreview) {
        $("service-status").textContent = 'Local preview: online submission is not configured. You can test labeling and download a backup.';
        renderGroupOptions();
      } else {
        $("service-status").textContent = error.message;
        $("start-form").hidden = true;
      }
      return offlinePreview;
    } finally { availabilityBusy = false; updateControls(); }
  }

  async function submitAnnotations() {
    if (!session || submitting || completed(group.id)) return;
    saveSelections(); persist(); progress();
    const pending = group.image_ids.findIndex(id => !isComplete(session.annotations[id]));
    if (pending >= 0) {
      navigate(pending);
      $("form-error").textContent = 'Select an answer for every image before submitting.';
      return;
    }
    const payload = JSON.parse(JSON.stringify(session));
    submitting = true; updateControls();
    $("export-status").textContent = 'Sending your annotations. Please wait for confirmation…';
    try {
      const receipt = await apiRequest('POST', payload);
      if (!receipt.submitted || receipt.submission_id !== payload.submission_id) throw new Error('The submission could not be confirmed. Retry to confirm it was received.');
      session.submission_receipt = receipt;
      groupStates[group.id] = {state: 'completed'};
      persist(); renderGroupOptions(); progress();
      $("export-status").textContent = 'Your annotations have been submitted successfully. Thank you!';
    } catch (error) {
      if (error.code === 'group_completed') {
        groupStates[group.id] = {state: 'completed'};
        renderGroupOptions(); progress();
      }
      $("export-status").textContent = error.message || 'Submission failed. Your answers remain saved in this browser; please retry.';
    } finally { submitting = false; updateControls(); }
  }

  $("submit-annotations").onclick = submitAnnotations;
  $("refresh-groups").onclick = refreshAvailability;

  $("export-json").onclick = () => download("json");
  $("export-csv").onclick = () => download("csv");
  document.addEventListener("visibilitychange", () => { if (document.hidden) { saveSelections(); persist(); } else viewStarted = performance.now(); });
  window.addEventListener("pagehide", () => { saveSelections(); persist(); });

  async function load() {
    try {
      const response = await fetch(new URL("study.json", assetBase), {cache: "no-store"});
      if (!response.ok) throw Error("Study settings could not be loaded.");
      study = await response.json(); showGuide();
      const dataResponse = await fetch(new URL("data/dataset.json", assetBase), {cache: "no-store"});
      if (!dataResponse.ok) { $("loading").textContent = "The labeling interface is ready for setup. The organizer has not yet prepared the image groups."; return; }
      dataset = await dataResponse.json();
      if (!dataset.groups?.length || !dataset.images || !dataset.study) throw Error("The dataset is incomplete.");
      study = dataset.study; showGuide();
      $("refresh-groups").disabled = false;
      await refreshAvailability();
      setInterval(() => { if (!document.hidden && !submitting) refreshAvailability(); }, 30000);
      document.addEventListener('visibilitychange', () => { if (!document.hidden && !submitting) refreshAvailability(); });
    } catch (error) { $("loading").textContent = `${error.message} Open this page through the website or a local web server, not by double-clicking the HTML file.`; }
  }
  load();
})();
