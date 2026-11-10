'use client';
import { Suspense } from 'react';
import Crud from './crud';
import { Loading } from './ui';

export default function CrudPage({ cfg }) {
  return <Suspense fallback={<Loading />}><Crud cfg={cfg} /></Suspense>;
}
