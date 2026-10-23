import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Account = { id:number; username:string; status:string };
function App() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  useEffect(() => { fetch('/api/v1/accounts').then(r => r.json()).then(v => setAccounts(v.accounts ?? [])).catch(() => setAccounts([])); }, []);
  return <main><header><h1>LLM Auth Bridge</h1><nav>Accounts · Targets · Tasks · Settings</nav></header><section><h2>Accounts</h2>{accounts.length ? <table><tbody>{accounts.map(a => <tr key={a.id}><td>{a.username}</td><td>{a.status}</td></tr>)}</tbody></table> : <p>No accounts imported.</p>}</section></main>;
}
createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
