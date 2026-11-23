"use strict";

const ui = Object.fromEntries([...document.querySelectorAll("[id]")].map(node => [node.id, node]));
let link = location.hash.slice(1);
history.replaceState(null, "", location.pathname);
let state;
let context = null;
let messages = [];
let pending = false;

async function api(path, data) {
  const options = data === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  };
  let response;
  try {
    response = await fetch("/api/" + path, options);
  } catch {
    throw new Error("Synta is unavailable. Open the website again from the overlay.");
  }
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error);
    error.status = response.status;
    throw error;
  }
  return result;
}

function showSnapshot(title) {
  ui.snapshot.textContent = title || "No snapshot attached";
  ui.detach.hidden = !title;
  ui["overlay-help"].hidden = Boolean(title);
}

function resetChat() {
  messages = [];
  for (const message of ui.log.querySelectorAll(".message")) message.remove();
  ui.welcome.hidden = false;
  ui.question.value = "";
  ui["chat-status"].textContent = "";
}

async function showWorkspace(name) {
  if (link) {
    try {
      const attachment = await api("context", { link });
      context = attachment.context;
      showSnapshot(attachment.title);
    } catch (error) {
      ui["context-error"].textContent = error.message;
    }
    link = "";
  }
  ui.auth.hidden = true;
  ui.account.hidden = ui.desk.hidden = false;
  ui.username.textContent = name;
  ui.model.textContent = state.model;
  ui.question.focus();
}

function showLogin(message = "") {
  context = null;
  showSnapshot(null);
  resetChat();
  ui["context-error"].textContent = "";
  ui.account.hidden = ui.desk.hidden = true;
  ui.auth.hidden = false;
  const title = state.setup ? "Create your account" : "Sign in";
  ui["auth-title"].textContent = ui["auth-submit"].textContent = title;
  ui["auth-copy"].textContent = state.setup
    ? "Set up your local login. Use at least 12 characters for your password."
    : "Use your local Synta account to open the tutor.";
  ui.password.autocomplete = state.setup ? "new-password" : "current-password";
  ui.password.minLength = state.setup ? 12 : 0;
  ui.password.value = "";
  ui["auth-error"].textContent = message;
  ui.name.focus();
}

ui.login.addEventListener("submit", async event => {
  event.preventDefault();
  ui["auth-submit"].disabled = true;
  ui["auth-error"].textContent = "";
  try {
    const result = await api(state.setup ? "setup" : "login", {
      name: ui.name.value,
      password: ui.password.value,
      link,
    });
    ui.password.value = "";
    state.setup = false;
    await showWorkspace(result.name);
  } catch (error) {
    ui["auth-error"].textContent = error.message;
  } finally {
    ui["auth-submit"].disabled = false;
  }
});

ui.logout.addEventListener("click", async () => {
  try {
    await api("logout", {});
    showLogin();
  } catch (error) {
    if (error.status === 401) showLogin();
    else ui["chat-status"].textContent = error.message;
  }
});

function append(author, text, isTutor = false) {
  ui.welcome.hidden = true;
  const message = document.createElement("article");
  message.className = isTutor ? "message tutor" : "message";
  const label = document.createElement("strong");
  const body = document.createElement("p");
  label.textContent = author;
  body.textContent = text;
  message.append(label, body);
  ui.log.append(message);
  ui.log.scrollTop = ui.log.scrollHeight;
}

ui.composer.addEventListener("submit", async event => {
  event.preventDefault();
  const question = ui.question.value.trim();
  if (!question || pending) return;
  pending = true;
  ui.send.disabled = ui.reset.disabled = ui.detach.disabled = ui.logout.disabled = true;
  ui.question.readOnly = true;
  ui["chat-status"].textContent = "Ollama is thinking…";
  try {
    const { reply } = await api("chat", { question, history: messages.slice(-16), context });
    append("You", question);
    append("Synta", reply, true);
    messages.push({ role: "user", content: question }, { role: "assistant", content: reply.slice(0, 4000) });
    messages = messages.slice(-16);
    ui.question.value = "";
    ui["chat-status"].textContent = "";
  } catch (error) {
    if (error.status === 401) showLogin("Your session ended. Sign in again.");
    else ui["chat-status"].textContent = error.message;
  } finally {
    pending = false;
    ui.send.disabled = ui.reset.disabled = ui.detach.disabled = ui.logout.disabled = false;
    ui.question.readOnly = false;
    if (!ui.desk.hidden) ui.question.focus();
  }
});

ui.question.addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    ui.composer.requestSubmit();
  }
});

ui.reset.addEventListener("click", () => {
  resetChat();
  ui.question.focus();
});

ui.detach.addEventListener("click", () => {
  context = null;
  showSnapshot(null);
  resetChat();
  ui.question.focus();
});

for (const button of document.querySelectorAll("[data-prompt]")) {
  button.addEventListener("click", () => {
    if (pending) return;
    ui.question.value = button.dataset.prompt;
    ui.question.focus();
  });
}

async function start() {
  try {
    state = await api("session");
    ui.loading.hidden = true;
    if (state.name) await showWorkspace(state.name);
    else showLogin(state.setup && !link ? "Open the website from the overlay to create your account." : "");
  } catch (error) {
    ui.loading.textContent = error.message;
  }
}

start();
