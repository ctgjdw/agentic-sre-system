export type Post = {
  id: number;
  author: string;
  content: string;
  likes: number;
  created_at: string;
};

export type PostsResponse = { posts: Post[] };

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export async function fetchPosts(limit = 50): Promise<Post[]> {
  if (!API_BASE) throw new Error("NEXT_PUBLIC_API_URL is not set at build time.");
  const res = await fetch(`${API_BASE}/posts?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetch /posts failed: ${res.status}`);
  const body = (await res.json()) as PostsResponse;
  return body.posts;
}
