import { FC } from 'react';
import { AppSidebarContent } from './AppSidebar';
import { HarborLogo } from './HarborLogo';
import { AppContent } from './AppContent';

export const DRAWER_ID = "app-drawer";

export const App: FC = () => {
    return <div className="flex h-screen w-screen overflow-hidden bg-base-100">
        <div className="drawer h-screen">
            <input id={DRAWER_ID} type="checkbox" className="drawer-toggle" />
            <div className="drawer-content flex flex-col h-screen">
                <div className="navbar w-full border-base-content/10 border-b-2">
                    <div className="flex-none lg:hidden">
                        <label htmlFor={DRAWER_ID} aria-label="open sidebar" className="btn btn-square btn-ghost">
                            <svg
                                xmlns="http://www.w3.org/2000/svg"
                                fill="none"
                                viewBox="0 0 24 24"
                                className="inline-block h-6 w-6 stroke-current">
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth="2"
                                    d="M4 6h16M4 12h16M4 18h16"></path>
                            </svg>
                        </label>
                    </div>
                    <div className="mx-2 flex-1 px-2">
                        <HarborLogo />
                    </div>
                    <div className="hidden flex-none lg:block">
                        <ul className="menu menu-horizontal gap-2">
                            <AppSidebarContent />
                        </ul>
                    </div>
                </div>
                <div className="flex-1 overflow-y-auto">
                    <div className="p-6">
                        <AppContent />
                    </div>
                </div>
            </div>
            <div className="drawer-side z-20">
                <label htmlFor={DRAWER_ID} aria-label="close sidebar" className="drawer-overlay"></label>
                <ul className="menu bg-base-200 min-h-full w-80 p-4 gap-2">
                    <AppSidebarContent />
                </ul>
            </div>
        </div>
    </div>
}
