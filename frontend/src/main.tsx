import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

// 移除 React.StrictMode 避免开发环境下重复渲染导致闪烁
// StrictMode 会导致 useEffect 执行两次，可能引起闪烁问题
ReactDOM.createRoot(document.getElementById('root')!).render(
  <App />
);
