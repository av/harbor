import { FC } from 'react';
import { Route, Routes } from 'react-router-dom';
import { ROUTES_LIST } from './AppRoutes';

export const AppContent: FC = () => {
  return <Routes>
    {ROUTES_LIST.map((route) => <Route key={route.id} {...route} />)}
  </Routes>
}
