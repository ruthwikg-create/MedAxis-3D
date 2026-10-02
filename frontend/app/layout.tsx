import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MedAxis 3D — Medical Imaging Workstation",
  description: "Advanced Multimodal Medical Imaging & 3D Analysis Workstation"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
