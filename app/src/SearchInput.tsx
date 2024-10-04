import { HTMLAttributes, useRef } from 'react';
import { KEY_CODES, KeyMatch, useGlobalKeydown } from './useGlobalKeydown';

const searchShortcut: KeyMatch = {
  key: KEY_CODES.F,
  ctrlKey: true,
};

export const SearchInput = ({ ...rest }: HTMLAttributes<HTMLInputElement>) => {
  const inputRef = useRef<HTMLInputElement>(null);

  useGlobalKeydown(searchShortcut, (e) => {
    e.preventDefault();
    inputRef.current?.focus();
  })


  return <label className="input input-ghost input-sm bg-base-200 flex items-center gap-2 rounded-box">
    <input ref={inputRef} type="text" className="grow" placeholder="Search" {...rest} />
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 16 16"
      fill="currentColor"
      className="h-4 w-4 opacity-70">
      <path
        fillRule="evenodd"
        d="M9.965 11.026a5 5 0 1 1 1.06-1.06l2.755 2.754a.75.75 0 1 1-1.06 1.06l-2.755-2.754ZM10.5 7a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0Z"
        clipRule="evenodd" />
    </svg>
  </label>
}
