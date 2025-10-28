import { database, ref, push, set } from "./firebase.js";

function saveScoreToFirebase(name, score, timeTaken) {
  const leaderboardRef = ref(database, "scores");
  const newScoreRef = push(leaderboardRef);
  set(newScoreRef, {
    name: name,
    score: score,
    time: timeTaken,
    timestamp: Date.now()
  });
}
