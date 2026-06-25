/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext } from 'react';

const RegistryContext = createContext(null);

export function useRegistry() {
  return useContext(RegistryContext);
}

export default RegistryContext;
