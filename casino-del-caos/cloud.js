// Casino del Caos: conexión con Firebase (login del administrador + sincronización iPad/iPhone).
// Ofrece la misma interfaz que la página ya usa (window.claude.use('db') y use('room')),
// pero guardando todo en Firestore. Solo la cuenta del administrador tiene permiso (reglas en Firebase).
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import { getAuth, onAuthStateChanged, GoogleAuthProvider, signInWithPopup, signInWithRedirect, getRedirectResult, signOut } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import { getFirestore, doc, getDoc, setDoc, onSnapshot, collection, addDoc, deleteDoc } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";

const firebaseConfig = {
  apiKey: "AIzaSyChoIBMvdypkPt1Sc_rYFJbDYW_sm9ldQ8",
  authDomain: "bertil-raxon.firebaseapp.com",
  projectId: "bertil-raxon",
  storageBucket: "bertil-raxon.firebasestorage.app",
  messagingSenderId: "328142754092",
  appId: "1:328142754092:web:93c9d31db80539259fdc89"
};
const BASE = "apps/casino-del-caos";

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const fs = getFirestore(app);
const resolveCloud = window.__cloudResolve || (() => {});
const $ = (s) => document.querySelector(s);

let user = null;
let allowed = false;
let firstAuth = true;

/* ---------- Cuenta del administrador (sección en Ajustes) ---------- */
function renderAccount() {
  const st = $("#adminStatus"), btn = $("#adminBtn");
  if (!st || !btn) return;
  btn.disabled = false;
  if (!user) {
    st.textContent = "No has entrado. Entrá con tu cuenta de Google para usar Pantalla y Control.";
    btn.textContent = "Entrar con Google";
  } else if (!allowed) {
    st.textContent = "Entraste como " + (user.email || "otra cuenta") + ", pero esa cuenta no tiene permiso de administrador.";
    btn.textContent = "Cerrar sesión";
  } else {
    st.textContent = "Entraste como " + user.email + ". Este dispositivo puede usar Pantalla y Control.";
    btn.textContent = "Cerrar sesión";
  }
}
async function signIn() {
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  try {
    await signInWithPopup(auth, provider); // al cambiar la sesión, la página se recarga sola (onAuthStateChanged)
  } catch (e) {
    const code = (e && e.code) || "";
    if (code === "auth/popup-blocked" || code === "auth/operation-not-supported-in-this-environment" || code === "auth/web-storage-unsupported") {
      await signInWithRedirect(auth, provider);
    } else if (code !== "auth/popup-closed-by-user" && code !== "auth/cancelled-popup-request") {
      const st = $("#adminStatus");
      if (st) st.textContent = "No se pudo entrar (" + code + "). Probá otra vez.";
    }
  }
}
document.addEventListener("click", (ev) => {
  const btn = ev.target && ev.target.closest && ev.target.closest("#adminBtn");
  if (!btn) return;
  if (user) signOut(auth);
  else signIn();
});

/* ---------- Puente de datos: db (estado guardado) ---------- */
const mapErr = (e) => ({ code: e && e.code === "permission-denied" ? "revoked" : "unavailable", message: (e && e.message) || "" });
const snapOf = (s) => ({ id: s.id, exists: s.exists(), data: () => s.data(), metadata: { fromCache: s.metadata.fromCache, hasPendingWrites: s.metadata.hasPendingWrites } });
const dbApi = {
  doc(path) {
    const ref = doc(fs, BASE + "/" + path);
    return {
      id: ref.id, path,
      get: () => getDoc(ref).then(snapOf).catch((e) => { throw mapErr(e); }),
      set: (data) => setDoc(ref, data).catch((e) => { throw mapErr(e); }),
      onSnapshot: (next, error) => onSnapshot(ref, (s) => next(snapOf(s)), (e) => error && error(mapErr(e))),
    };
  },
};

/* ---------- Puente en vivo: room (comandos del iPhone y pantalla del iPad) ---------- */
const PEER = Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
function makeRoom() {
  const handlers = {}, peerFns = [], connFns = [];
  let mine = {}, peers = new Map(), viewUnsub = null, cmdUnsub = null;
  let lastViewKey = null, lastViewAt = 0, viewTimer = null, pendingView = null;
  const presRef = doc(fs, BASE + "/presence/" + PEER);
  const viewRef = doc(fs, BASE + "/room/view");
  const cmdsCol = collection(fs, BASE + "/cmds");
  const connected = () => navigator.onLine && !!user && allowed;
  const msg = (topic, data, peer) => ({ topic, data, peer, by: null, isMe: true, sameTab: false, kind: "viewer", guest: false });
  const deliver = (topic, data, peer) => (handlers[topic] || []).forEach((fn) => { try { fn(msg(topic, data, peer)); } catch (e) { console.error(e); } });

  function list() {
    const now = Date.now();
    const out = [{ peer: PEER, by: null, isMe: true, sameTab: true, kind: "viewer", guest: false, presence: mine, updatedAt: now }];
    peers.forEach((p, id) => { if (id !== PEER && now - (p.t || 0) < 60000) out.push({ peer: id, by: null, isMe: true, sameTab: false, kind: "viewer", guest: false, presence: { role: p.role }, updatedAt: p.t || 0 }); });
    return out;
  }
  function firePeers() { const ps = list(); peerFns.forEach((f) => { try { f({ peers: ps, joined: [], left: [], updated: [] }); } catch (e) { console.error(e); } }); }
  async function beat() { if (!connected()) return; try { await setDoc(presRef, { role: mine.role || "solo", t: Date.now() }); } catch (e) {} }

  onSnapshot(collection(fs, BASE + "/presence"), (snap) => {
    const m = new Map(), now = Date.now();
    snap.forEach((d) => {
      const p = d.data() || {};
      if (now - (p.t || 0) > 3600000) { deleteDoc(d.ref).catch(() => {}); return; } // limpia dispositivos viejos
      m.set(d.id, p);
    });
    peers = m; firePeers();
  }, () => {});
  setInterval(firePeers, 15000);
  setInterval(beat, 20000);
  window.addEventListener("pagehide", () => { deleteDoc(presRef).catch(() => {}); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) beat(); });
  const fireConn = () => connFns.forEach((f) => { try { f(connected()); } catch (e) {} });
  window.addEventListener("online", () => { fireConn(); beat(); });
  window.addEventListener("offline", fireConn);

  function writeView(v) {
    lastViewAt = Date.now();
    lastViewKey = JSON.stringify({ ...v, cur: { ...v.cur, tl: 0 } });
    setDoc(viewRef, { v: JSON.stringify(v), peer: PEER, t: lastViewAt }).catch(() => {});
  }
  function ensure(topic) {
    if (topic === "view" && !viewUnsub) {
      viewUnsub = onSnapshot(viewRef, (s) => {
        if (!s.exists()) return; const d = s.data();
        if (!d || d.peer === PEER || typeof d.v !== "string") return;
        try { deliver("view", JSON.parse(d.v), d.peer); } catch (e) {}
      }, () => {});
    }
    if (topic === "cmd" && !cmdUnsub) {
      cmdUnsub = onSnapshot(cmdsCol, (snap) => {
        snap.docChanges().forEach((ch) => {
          if (ch.type !== "added") return;
          const d = ch.doc.data(); if (!d || d.peer === PEER) return;
          const isHost = mine.role === "pantalla";
          if (Date.now() - (d.t || 0) < 60000 && typeof d.v === "string") { try { deliver("cmd", JSON.parse(d.v), d.peer); } catch (e) {} }
          if (isHost) deleteDoc(ch.doc.ref).catch(() => {});
        });
      }, () => {});
    }
  }
  return {
    emit(topic, data) {
      if (!connected()) return Promise.resolve();
      if (topic === "view") {
        const key = JSON.stringify({ ...data, cur: { ...data.cur, tl: 0 } });
        const now = Date.now();
        if (key === lastViewKey && now - lastViewAt < 5000) {
          pendingView = data;
          if (!viewTimer) viewTimer = setTimeout(() => { viewTimer = null; if (pendingView) { const v = pendingView; pendingView = null; writeView(v); } }, 5000 - (now - lastViewAt));
          return Promise.resolve();
        }
        pendingView = null; writeView(data); return Promise.resolve();
      }
      return addDoc(cmdsCol, { v: JSON.stringify(data), peer: PEER, t: Date.now() }).then(() => {}).catch((e) => { throw mapErr(e); });
    },
    on(topic, fn) { (handlers[topic] = handlers[topic] || []).push(fn); ensure(topic); return () => { handlers[topic] = (handlers[topic] || []).filter((f) => f !== fn); }; },
    presence(patch) { mine = { ...mine, ...patch }; beat(); firePeers(); return Promise.resolve(); },
    onPeers(fn) { peerFns.push(fn); setTimeout(() => { const ps = list(); fn({ peers: ps, joined: ps, left: [], updated: [] }); }, 0); return () => {}; },
    peers: list,
    connected,
    onConnection(fn) { connFns.push(fn); setTimeout(() => fn(connected()), 0); return () => {}; },
  };
}

let roomApi = null;
const api = { use: (name) => (name === "db" ? dbApi : name === "room" ? (roomApi = roomApi || makeRoom()) : null) };

getRedirectResult(auth).catch(() => {});
onAuthStateChanged(auth, async (u) => {
  const before = user ? user.uid : null;
  user = u;
  if (!firstAuth) { if ((u ? u.uid : null) !== before) location.reload(); return; }
  firstAuth = false;
  if (!u) { allowed = false; renderAccount(); resolveCloud(null); return; }
  try { await getDoc(doc(fs, BASE + "/torneo/v2")); allowed = true; }
  catch (e) { allowed = !(e && e.code === "permission-denied"); }
  renderAccount();
  resolveCloud(allowed ? api : null);
});
renderAccount();
