const app = document.querySelector<HTMLDivElement>("#app");

if (app) {
  app.innerHTML = `
    <main>
      <h1>Lantern</h1>
      <p>Dashboard scaffold. The camera feed, voice transcript, proposed-action panel,
      Life Graph panel, and audit log land in a later build stage.</p>
    </main>
  `;
}
