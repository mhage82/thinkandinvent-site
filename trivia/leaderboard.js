import { db, ref, onValue } from "./firebase.js";

const leaderboardSection = document.getElementById("leaderboard");
const leaderboardBody = document.getElementById("leaderboard-body");

function renderLeaderboard(players) {
  players.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    return a.totalTimeSeconds - b.totalTimeSeconds;
  });

  const top3 = players.slice(0, 3);
  leaderboardBody.innerHTML = "";
  top3.forEach((p, i) => {
    const medal = ["🥇", "🥈", "🥉"][i] || i + 1;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${medal}</td>
      <td>${p.name}</td>
      <td>${p.score}</td>
      <td>${p.totalTimeSeconds}</td>
    `;
    leaderboardBody.appendChild(tr);
  });

  leaderboardSection.classList.remove("hidden");
}

// Live listener — automatically updates all browsers in real time
onValue(ref(db, "scores"), (snapshot) => {
  const data = snapshot.val() || {};
  const players = Object.values(data);
  renderLeaderboard(players);
});
