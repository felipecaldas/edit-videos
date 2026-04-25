# Supabase Storage RLS Setup Guide

This document explains how to configure Row-Level Security (RLS) policies for the Supabase Storage bucket used by the image generation workflow.

## Overview

The image generation workflow uploads images to Supabase Storage using **user JWT tokens** instead of a service role key. This approach:

- ✅ Respects Row-Level Security policies
- ✅ Ensures users can only access their own files
- ✅ Follows security best practices (no service_role key exposure)
- ✅ Provides proper audit trails

## Required RLS Policies

You need to configure the following RLS policies in your Supabase project for the `storage.objects` table.

### 1. Allow Authenticated Users to Upload to Their Own Folder

This policy allows authenticated users to upload files to their own user folder.

```sql
CREATE POLICY "Users can upload to their own folder"
ON storage.objects
FOR INSERT
TO authenticated
WITH CHECK (
  bucket_id = 'user-videos' 
  AND (storage.foldername(name))[1] = auth.uid()::text
);
```

**Explanation:**
- `FOR INSERT` - Applies to file uploads
- `TO authenticated` - Only applies to authenticated users (with valid JWT)
- `bucket_id = 'user-videos'` - Restricts to the user-videos bucket
- `(storage.foldername(name))[1] = auth.uid()::text` - Ensures the first folder in the path matches the user's ID

### 2. Allow Authenticated Users to Read Their Own Files

This policy allows users to read/download files from their own folder.

```sql
CREATE POLICY "Users can read their own files"
ON storage.objects
FOR SELECT
TO authenticated
USING (
  bucket_id = 'user-videos'
  AND (storage.foldername(name))[1] = auth.uid()::text
);
```

### 3. Allow Authenticated Users to Update Their Own Files

This policy allows users to update/overwrite files in their own folder.

```sql
CREATE POLICY "Users can update their own files"
ON storage.objects
FOR UPDATE
TO authenticated
USING (
  bucket_id = 'user-videos'
  AND (storage.foldername(name))[1] = auth.uid()::text
)
WITH CHECK (
  bucket_id = 'user-videos'
  AND (storage.foldername(name))[1] = auth.uid()::text
);
```

### 4. Allow Authenticated Users to Delete Their Own Files

This policy allows users to delete files from their own folder.

```sql
CREATE POLICY "Users can delete their own files"
ON storage.objects
FOR DELETE
TO authenticated
USING (
  bucket_id = 'user-videos'
  AND (storage.foldername(name))[1] = auth.uid()::text
);
```

## Bucket Configuration

Ensure your `user-videos` bucket is configured with:

1. **Public bucket**: `false` (files are private by default)
2. **File size limit**: Set according to your needs (e.g., 10MB for images)
3. **Allowed MIME types**: `image/png`, `image/jpeg`, `image/webp` (optional restriction)

## Storage Path Structure

The application uploads files using the following path structure:

```
{user_id}/{run_id}/{filename}
```

Example:
```
13289527-075a-42da-9ddb-357f8634553b/2fduqlf3tgh/image_001.png
```

Where:
- `user_id` - Supabase Auth user UUID
- `run_id` - Unique workflow run identifier (6-character hex)
- `filename` - Sequential image filename (e.g., `image_001.png`)

## How It Works

1. **Frontend**: User authenticates with Supabase Auth and obtains a JWT access token
2. **API Request**: Frontend sends the JWT token in the `user_access_token` field when calling `/orchestrate/generate-images`
3. **Backend**: The Temporal workflow passes the JWT to the `persist_image_output` activity
4. **Storage Upload**: The activity creates a `SupabaseStorageClient` with the user's JWT and uploads the file
5. **RLS Check**: Supabase verifies the JWT and checks RLS policies before allowing the upload

## Testing RLS Policies

To test that RLS is working correctly:

1. **Test with valid user JWT**: Upload should succeed
2. **Test with different user's JWT**: Upload should fail (403 Forbidden)
3. **Test with expired JWT**: Upload should fail (401 Unauthorized)
4. **Test with anon key only**: Upload should fail (RLS policy not satisfied)

## Troubleshooting

### Error: "new row violates row-level security policy"

**Cause**: The user's JWT doesn't satisfy the RLS policy conditions.

**Solutions**:
- Verify the JWT is valid and not expired
- Check that `auth.uid()` in the JWT matches the `user_id` in the upload path
- Ensure the bucket_id is correct (`user-videos`)
- Verify RLS policies are enabled and correctly configured

### Error: "User JWT is required for uploads"

**Cause**: The `user_access_token` was not provided in the API request.

**Solution**: Ensure the frontend is passing the user's JWT token in the request body.

## Security Considerations

1. **Never expose service_role key**: The service role key bypasses all RLS and should only be used in trusted server environments
2. **JWT expiration**: User JWTs expire after 1 hour by default. Ensure your frontend refreshes tokens as needed
3. **HTTPS only**: Always use HTTPS to prevent JWT interception
4. **Validate user_id**: The backend should validate that the `user_id` in the request matches the JWT's `sub` claim

## References

- [Supabase Storage RLS Documentation](https://supabase.com/docs/guides/storage/security/access-control)
- [Supabase Auth Documentation](https://supabase.com/docs/guides/auth)
- [PostgreSQL RLS Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
