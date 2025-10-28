import { database, ref, onValue } from "./firebase.js";

export function startLeaderboardUpdates() {
  const leaderboardRef = ref(database, "scores");
  const leaderboardTable = document.getElementById("leaderboard");

  onValue(leaderboardRef, (snapshot) => {
    const data = snapshot.val();
    if (!data) return;
    const scores = Object.values(data)
      .sort((a, b) => b.score - a.score || a.time - b.time)
      .slice(0, 3);

    leaderboardTable.innerHTML = `
      <table class="leaderboard-table">
        <tr><th>Rank</th><th>Name</th><th>Score</th><th>Time</th></tr>
        ${scores
          .map(
            (s, i) =>
              `<tr><td>${i + 1}</td><td>${s.name}</td><td>${s.score}</td><td>${(s.time / 1000).toFixed(2)}s</td></tr>`
          )
          .join("")}
      </table>
    `;
  });
}
