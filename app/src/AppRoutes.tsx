import { ReactNode } from "react";
import { RouteProps } from "react-router-dom";

import { Config } from "./config/Config";
import { Home } from "./home/Home";
import { Settings } from "./settings/Settings";
import { IconBolt, IconLayoutDashboard, IconSettings, IconTerminal } from "./Icons";
import { CLI } from "./cli/CLI";

type HarborRoute = {
    id: string;
    name: ReactNode;
} & RouteProps;

export const ROUTES: Record<string, HarborRoute> = {
    home: {
        id: 'home',
        name: <span className="flex items-center gap-2"><IconLayoutDashboard />Home</span>,
        path: '/',
        element: <Home />,
    },
    config: {
        id: 'config',
        name: <span className="flex items-center gap-2"><IconBolt />Profiles</span>,
        path: '/config',
        element: <Config />,
    },
    cli: {
        id: 'cli',
        name: <div className="flex items-center gap-2"><IconTerminal />CLI</div>,
        path: '/cli',
        element: <CLI />,
    },
    settings: {
        id: 'settings',
        name: <span className="flex items-center gap-2"><IconSettings />Settings</span>,
        path: '/settings',
        element: <Settings />,
    },
};

export const ROUTE_NAMES = {
    home: 'Home',
    config: 'Config',
    settings: 'Settings',
};

export const ROUTES_LIST = Object.values(ROUTES);