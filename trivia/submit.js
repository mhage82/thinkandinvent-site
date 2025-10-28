// submit.js
import { database, ref, push, set } from "./firebase.js";

export async function submitResults(playerName, score, elapsedTimeMs) {
  try {
    const leaderboardRef = ref(database, "scores");
    const newEntryRef = push(leaderboardRef);
    await set(newEntryRef, {
      name: playerName,
      score: score,
      time: elapsedTimeMs,
      submittedAt: Date.now()
    });

    console.log("✅ Saved to Firebase successfully!");
    return true;
  } catch (error) {
    console.error("❌ Firebase save failed:", error);
    return false;
  }
}
