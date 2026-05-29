import './index.css'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { Amplify } from 'aws-amplify'
import { cognitoUserPoolsTokenProvider } from 'aws-amplify/auth/cognito'
import App from './App'

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
      userPoolClientId: import.meta.env.VITE_COGNITO_CLIENT_ID,
      ...(import.meta.env.VITE_COGNITO_ENDPOINT
        ? { endpoint: import.meta.env.VITE_COGNITO_ENDPOINT }
        : {}),
    },
  },
})

// Tokens are tab-scoped — cleared when the tab closes
cognitoUserPoolsTokenProvider.setKeyValueStorage({
  getItem: (k) => sessionStorage.getItem(k),
  setItem: (k, v) => sessionStorage.setItem(k, v),
  removeItem: (k) => sessionStorage.removeItem(k),
  clear: () => sessionStorage.clear(),
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
