"use strict";
// Onglet Réglages : compte ScoDoc dédié. Le mot de passe part vers le serveur
// local qui le range dans le trousseau du système ; il n'est jamais relu.

(() => {
  const { $, api, guard, onTab } = window.QCM;
  const form = $("#scodoc-settings");
  const deleteButton = $("#scodoc-delete");

  function message(text, cls = "status") {
    const status = $("#scodoc-settings-status");
    status.className = cls;
    status.textContent = text;
  }

  function show(account) {
    form.elements.url.value = account.url || "";
    form.elements.username.value = account.username || "";
    form.elements.password.value = "";
    form.elements.password.required = !account.has_password;
    form.elements.password.placeholder = account.has_password ? "Enregistré (laisser vide pour le conserver)" : "";
    $("#keyring-name").textContent = account.keyring;
    $("#scodoc-password-state").textContent = account.has_password
      ? "Mot de passe enregistré dans le trousseau."
      : "Aucun mot de passe enregistré.";
    $("#scodoc-test").disabled = !account.complete;
    deleteButton.disabled = !account.username;
    delete deleteButton.dataset.confirm;
    deleteButton.textContent = "Supprimer le compte";
  }

  onTab("settings", () => guard(async () => show(await api("GET", "/api/settings/scodoc"))));

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    guard(async () => {
      const { url, username, password } = form.elements;
      try {
        show(await api("PUT", "/api/settings/scodoc", { url: url.value, username: username.value, password: password.value }));
        message("Compte ScoDoc enregistré.", "status ok");
      } catch (error) {
        message(error.message, "status error");
      } finally {
        password.value = "";
      }
    });
  });

  $("#scodoc-test").addEventListener("click", () => guard(async () => {
    message("Connexion à ScoDoc…");
    try {
      message((await api("POST", "/api/settings/scodoc/test")).message, "status ok");
    } catch (error) {
      message(error.message, "status error");
    }
  }));

  // Suppression en deux clics (pas de boîte de confirmation du navigateur).
  deleteButton.addEventListener("click", () => guard(async () => {
    if (!deleteButton.dataset.confirm) {
      deleteButton.dataset.confirm = "1";
      deleteButton.textContent = "Confirmer la suppression";
      return;
    }
    show(await api("DELETE", "/api/settings/scodoc"));
    message("Compte ScoDoc supprimé (fichier de réglages et trousseau).", "status ok");
  }));
})();
