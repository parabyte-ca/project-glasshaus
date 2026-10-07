import { BrowserRouter, Route, Routes } from 'react-router';

import { AuthProvider } from './auth/AuthContext';
import { Layout } from './components/Layout';
import { HomePage } from './pages/HomePage';
import { ProjectPage } from './pages/ProjectPage';

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="projects/:projectKey" element={<ProjectPage />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
