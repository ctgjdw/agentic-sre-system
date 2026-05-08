"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Post } from "@/lib/api";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function PostsTable({ posts }: { posts: Post[] }) {
  if (posts.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">No posts yet.</p>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-16">ID</TableHead>
          <TableHead className="w-40">Author</TableHead>
          <TableHead>Content</TableHead>
          <TableHead className="w-20 text-right">Likes</TableHead>
          <TableHead className="w-48">Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {posts.map((p) => (
          <TableRow key={p.id}>
            <TableCell>{p.id}</TableCell>
            <TableCell>{p.author}</TableCell>
            <TableCell className="max-w-xl truncate">{p.content}</TableCell>
            <TableCell className="text-right">{p.likes}</TableCell>
            <TableCell>{formatDate(p.created_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
