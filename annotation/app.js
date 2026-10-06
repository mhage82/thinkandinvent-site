"use strict";
(() => {
  const assetBase = new URL('.', document.currentScript.src);
  const $ = id => document.getElementById(id);
  let study, dataset, group, session, index = 0, imageReady = false, viewStarted = 0;
  const now = () => new Date().toISOString();
  const choices = name => [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(el => el.value);
  const imageId = () => group.image_ids[index];
  const keyFor = (annotator, groupId) => `image-annotation:${dataset.dataset_id}:${groupId}:${annotator}`;
  const activeKey = () => keyFor(session.annotator_id, group.id);
  const isComplete = row => row?.status === "annotated" || row?.status === "image_unavailable";

  function textElement(tag, text, className) {
    const el = document.createElement(tag);
    el.textContent = text;
    if (className) el.className = className;
    return el;
  }

  function showGuide() {
    $("label-guide").replaceChildren();
    $("label-options").replaceChildren();
    $("usability-options").replaceChildren();
    for (const label of study.labels) {
      const card = textElement("article", "", "guide-card");
      card.append(textElement("h3", label.name), textElement("p", label.description), textElement("p", `Illustrative example: ${label.example}`));
      $("label-guide").append(card);
      addChoice($("label-options"), "checkbox", "artifact", label);
    }
    for (const option of study.usability) addChoice($("usability-options"), "radio", "usability", option);
    $("example-gallery").replaceChildren();
    for (const example of study.examples || []) {
      const figure = document.createElement("figure");
      const image = document.createElement("img");
      image.src = new URL(example.src, assetBase).href;
      image.alt = example.explanation;
      figure.append(image, textElement("figcaption", example.explanation));
      $("example-gallery").append(figure);
    }
    $("contact").textContent = study.contact ? `Questions or return of results: ${study.contact}` : "Organizer setup pending: add a contact and reviewed image examples before inviting students.";
    $("guide-version").textContent = `Guidelines ${study.guidelines_version}. Text examples above are illustrative; reviewed photo examples should be supplied by the organizer.`;
    $("return-instructions").textContent = study.return_instructions;
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
      $("storage-status").textContent = "Selections saved automatically. Save results downloads a copy.";
    } catch {
      $("storage-status").textContent = "Browser storage is unavailable or full. Your work is only in this tab; download results before leaving.";
    }
  }

  function saveSelections() {
    if (!session || !group) return;
    const id = imageId(), previous = session.annotations[id];
    const selected = choices("artifact");
    const values = {
      labels: selected.filter(x => x !== "none" && x !== "uncertain"),
      artifact_judgment: selected.includes("none") ? "none" : selected.includes("uncertain") ? "uncertain" : selected.length ? "present" : "",
      usability: choices("usability")[0] || "",
    };
    if (!previous && !selected.length && !values.usability) return;
    const changed = !previous || Object.keys(values).some(k => JSON.stringify(previous[k]) !== JSON.stringify(values[k]));
    const status = previous?.status === "image_unavailable" && !changed ? "image_unavailable" : values.artifact_judgment && values.usability ? "annotated" : "draft";
    const {confidence, notes, ...retained} = previous || {};
    session.annotations[id] = {
      ...retained, ...values, image_id: id, status,
      started_at: previous?.started_at || now(),
      updated_at: changed || previous?.status !== status ? now() : previous.updated_at,
      active_seconds: (previous?.active_seconds || 0) + Math.min(300, Math.max(0, (performance.now() - viewStarted) / 1000)),
    };
    viewStarted = performance.now();
  }

  function progress() {
    let annotated = 0, issues = 0;
    for (const id of group.image_ids) {
      if (session.annotations[id]?.status === "annotated") annotated++;
      if (session.annotations[id]?.status === "image_unavailable") issues++;
    }
    $("progress").max = group.image_ids.length;
    $("progress").value = annotated + issues;
    $("progress-text").textContent = `${annotated} labeled · ${issues} image issues · ${group.image_ids.length - annotated - issues} unfinished`;
    $("completion-heading").textContent = annotated + issues === group.image_ids.length ? "Group finished — save and return your results" : "Save your results at any time";
    $("jump").replaceChildren(...group.image_ids.map((id, n) => {
      const row = session.annotations[id];
      return new Option(`${n + 1}${row?.status === "annotated" ? " ✓" : row?.status === "image_unavailable" ? " !" : row ? " ·" : ""}`, String(n), false, n === index);
    }));
  }

  function render() {
    const id = imageId(), row = session.annotations[id];
    $("annotation-form").reset();
    for (const input of document.querySelectorAll('input[name="artifact"]')) input.checked = row?.labels?.includes(input.value) || row?.artifact_judgment === input.value;
    for (const name of ["usability"]) for (const input of document.querySelectorAll(`input[name="${name}"]`)) input.checked = input.value === row?.[name];
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
      for (const field of $("annotation-form").querySelectorAll("fieldset")) field.disabled = false;
      $("image-status").textContent = row?.status === "image_unavailable" ? "Previously reported unavailable. New selections will replace that report." : "";
    };
    photo.onerror = () => {
      if ($("photo") !== photo) return;
      $("image-status").textContent = "This image could not load. Check your connection or record an image issue; do not guess labels.";
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
    if (!targetGroup?.image_ids.length || !/^[A-Za-z0-9_-]{1,64}$/.test(value.annotator_id)) throw Error("Invalid or empty group, or invalid annotator code.");
    if (!value.annotations || Array.isArray(value.annotations) || typeof value.annotations !== "object") throw Error("Invalid annotations.");
    for (const [id, row] of Object.entries(value.annotations)) {
      if (!targetGroup.image_ids.includes(id) || row.image_id !== id || !["draft", "annotated", "image_unavailable"].includes(row.status)) throw Error("Results contain an invalid image or status.");
      if (!Array.isArray(row.labels) || new Set(row.labels).size !== row.labels.length || row.labels.some(x => !study.labels.some(l => l.id === x))) throw Error("Results contain an unknown or duplicate label.");
      if (!["", "none", "uncertain", "present"].includes(row.artifact_judgment) || (row.artifact_judgment === "present") !== (row.labels.length > 0)) throw Error("Artifact choices are inconsistent.");
      if (!["", ...study.usability.map(x => x.id)].includes(row.usability)) throw Error("Results contain an invalid answer.");
      if (row.status === "annotated" && (!row.artifact_judgment || !row.usability)) throw Error("A completed annotation is missing answers.");
      if (!Number.isFinite(row.active_seconds) || row.active_seconds < 0) throw Error("Invalid timing data.");
    }
    return value;
  }

  function begin(annotator, groupId, restored) {
    group = dataset.groups.find(x => x.id === groupId);
    if (!group?.image_ids.length) { $("loading").textContent = "This group has no images yet. Choose a populated group."; return; }
    session = restored || {schema_version: 1, dataset_id: dataset.dataset_id, guidelines_version: study.guidelines_version, annotator_id: annotator, group_id: groupId, started_at: now(), annotations: {}};
    index = Math.max(0, Math.min(group.image_ids.length - 1, Number(session.current_index) || 0));
    $("setup").hidden = true;
    $("workspace").hidden = false;
    document.body.classList.add("annotating");
    $("guide-content").append($("guidelines"));
    $("guidelines").open = true;
    // Older sessions retain their labels; confidence and notes are no longer collected.
    for (const row of Object.values(session.annotations)) {
      delete row.confidence; delete row.notes;
      if (row.status !== "image_unavailable") row.status = row.artifact_judgment && row.usability ? "annotated" : "draft";
    }
    window.scrollTo(0, 0);
    $("group-heading").textContent = `${group.name} · ${annotator}`;
    render();
  }

  $("start-form").addEventListener("submit", event => {
    event.preventDefault();
    const annotator = $("annotator").value.trim(), groupId = $("group").value;
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
  $("report-broken").addEventListener("click", () => {
    if (!confirm("Record this image as unavailable? This replaces any labels for this image with an issue report.")) return;
    saveSelections();
    session.annotations[imageId()] = {image_id: imageId(), labels: [], artifact_judgment: "", usability: "", status: "image_unavailable", started_at: session.annotations[imageId()]?.started_at || now(), updated_at: now(), active_seconds: session.annotations[imageId()]?.active_seconds || 0};
    // Clear controls before navigation so saving a draft cannot restore old labels.
    $("annotation-form").reset();
    persist(); navigate(Math.min(index + 1, group.image_ids.length - 1));
  });
  $("previous").onclick = () => navigate(index - 1);
  $("next").onclick = () => navigate(index + 1);
  $("jump").onchange = () => navigate(Number($("jump").value));
  $("first-pending").onclick = () => { const pending = group.image_ids.findIndex(id => !isComplete(session.annotations[id])); if (pending >= 0) navigate(pending); else $("export-status").textContent = "All images are labeled or reported unavailable. Download and return your results."; };
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
      const fields = ["dataset_id", "guidelines_version", "annotator_id", "group_id", "image_id", "filename", "status", "labels", "artifact_judgment", "usability", "active_seconds", "updated_at"];
      const cell = value => { let text = String(value ?? ""); if (/^[=+@\-\t\r\n]/.test(text)) text = "'" + text; return '"' + text.replaceAll('"', '""') + '"'; };
      body = fields.join(",") + "\r\n" + records.map(row => fields.map(field => cell(field === "labels" ? row.labels.join("|") : ["dataset_id", "guidelines_version", "annotator_id", "group_id"].includes(field) ? session[field] : row[field])).join(",")).join("\r\n"); type = "text/csv;charset=utf-8";
    }
    const url = URL.createObjectURL(new Blob([body], {type}));
    const a = document.createElement("a"); a.href = url; a.download = `${session.annotator_id}_${group.id}_${dataset.dataset_id}.${format}`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    $("export-status").textContent = `Download requested. Keep the file and send it to the organizer; it has not been submitted automatically.`;
  }
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
      for (const entry of dataset.groups) {
        const option = new Option(`${entry.name} (${entry.image_ids.length} images)`, entry.id);
        option.disabled = entry.image_ids.length === 0;
        $("group").add(option);
      }
      const available = dataset.groups.filter(x => x.image_ids.length > 0);
      const requested = new URLSearchParams(location.search).get("group");
      $("group").value = available.some(x => x.id === requested) ? requested : available[0]?.id || "";
      $("loading").textContent = available.length ? `${available.length} of ${dataset.groups.length} groups have images. Select only the group assigned to you.` : "All three groups are empty. Add images to the group folders and refresh the image list before labeling.";
      $("start-form").hidden = available.length === 0;
    } catch (error) { $("loading").textContent = `${error.message} Open this page through the website or a local web server, not by double-clicking the HTML file.`; }
  }
  load();
})();
