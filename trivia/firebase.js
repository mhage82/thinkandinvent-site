// Import Firebase modules (using CDN paths, so no npm install needed)
import { initializeApp } from "https://www.gstatic.com/firebasejs/11.0.0/firebase-app.js";
import { getDatabase, ref, push, onValue } from "https://www.gstatic.com/firebasejs/11.0.0/firebase-database.js";

// ✅ Your Firebase configuration (copied from your console)
const firebaseConfig = {
  apiKey: "AIzaSyAiXXAllCaHfQdJDc1tTKPX0fHZUH7HAao",
  authDomain: "lebanese-trivia.firebaseapp.com",
  databaseURL: "https://lebanese-trivia-default-rtdb.firebaseio.com",
  projectId: "lebanese-trivia",
  storageBucket: "lebanese-trivia.firebasestorage.app",
  messagingSenderId: "436910636749",
  appId: "1:436910636749:web:fe18a31cb2bd41232ab384",
  measurementId: "G-EJRQRVZH76"
};

// Initialize Firebase
export const app = initializeApp(firebaseConfig);
export const db = getDatabase(app);
export { ref, push, onValue };
