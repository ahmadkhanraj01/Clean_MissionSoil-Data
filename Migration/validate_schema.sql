--
-- PostgreSQL database dump
--

\restrict bbMiFCVAOTYwNrPidqXpeSuPoAhJG8qI98xjzAzeX30TFzZerUMlEo3bJahjgNS

-- Dumped from database version 14.24 (Ubuntu 14.24-1.pgdg22.04+2)
-- Dumped by pg_dump version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: validate; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA validate;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: attributes; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.attributes (
    id uuid NOT NULL,
    name text NOT NULL,
    title text,
    reference_url text,
    unit character varying(50),
    data_type character varying(50),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    record_id uuid NOT NULL
);


--
-- Name: distributions; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.distributions (
    id uuid NOT NULL,
    name text NOT NULL,
    format text,
    access_url text,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    record_id uuid NOT NULL
);


--
-- Name: landcover_types; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.landcover_types (
    code text NOT NULL,
    level smallint NOT NULL,
    parent_code text,
    name text NOT NULL,
    description text,
    CONSTRAINT landcover_types_level_check CHECK (((level >= 1) AND (level <= 3)))
);


--
-- Name: landuse_types; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.landuse_types (
    code text NOT NULL,
    level smallint NOT NULL,
    parent_code text,
    name text NOT NULL,
    description text,
    CONSTRAINT landuse_types_level_check CHECK (((level >= 1) AND (level <= 3)))
);


--
-- Name: organizations; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.organizations (
    id uuid NOT NULL,
    name text NOT NULL,
    aliases jsonb,
    phone_number character varying(50),
    ror_identifier character varying(100),
    street_address text,
    postal_code character varying(30),
    city character varying(100),
    state_or_region character varying(100),
    country character varying(100),
    website_url text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: person_organization; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.person_organization (
    id uuid NOT NULL,
    person_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: persons; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.persons (
    id uuid NOT NULL,
    name text NOT NULL,
    aliases jsonb,
    email character varying(255),
    orcid character varying(50),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: projects; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.projects (
    id uuid NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: recommendation_events; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.recommendation_events (
    id uuid NOT NULL,
    visitor_id uuid NOT NULL,
    role text NOT NULL,
    event_type text NOT NULL,
    query text,
    record_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: record_landcover; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.record_landcover (
    record_id uuid NOT NULL,
    codes text[] NOT NULL,
    probabilities text[] NOT NULL,
    l1_codes text[] DEFAULT '{}'::text[] NOT NULL,
    l2_codes text[] DEFAULT '{}'::text[] NOT NULL,
    l3_codes text[] DEFAULT '{}'::text[] NOT NULL,
    n_labels smallint NOT NULL,
    run_id text NOT NULL,
    classified_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: record_landuse; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.record_landuse (
    record_id uuid NOT NULL,
    codes text[] NOT NULL,
    probabilities text[] NOT NULL,
    l1_codes text[] DEFAULT '{}'::text[] NOT NULL,
    l2_codes text[] DEFAULT '{}'::text[] NOT NULL,
    l3_codes text[] DEFAULT '{}'::text[] NOT NULL,
    n_labels smallint NOT NULL,
    run_id text NOT NULL,
    classified_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: record_organization; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.record_organization (
    id uuid NOT NULL,
    record_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: record_person; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.record_person (
    id uuid NOT NULL,
    record_id uuid NOT NULL,
    person_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: record_project; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.record_project (
    id uuid NOT NULL,
    record_id uuid NOT NULL,
    project_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: record_source; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.record_source (
    id uuid NOT NULL,
    record_id uuid NOT NULL,
    source_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: record_subject; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.record_subject (
    id uuid NOT NULL,
    record_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: records; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.records (
    id uuid NOT NULL,
    identifier text NOT NULL,
    title text NOT NULL,
    abstract text,
    resource_type text,
    license text,
    language text,
    thumbnail text,
    publication_date timestamp with time zone,
    resource_creation_date timestamp with time zone,
    resource_updated_date timestamp with time zone,
    harvest_date timestamp with time zone,
    spatial text,
    temporal_start timestamp with time zone,
    temporal_end timestamp with time zone,
    raw_metadata jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    approval_status character varying(50) DEFAULT 'pending'::character varying NOT NULL,
    url text,
    CONSTRAINT records_url_format_ck CHECK (((url IS NULL) OR (url ~ '^https?://[^\s]+$'::text)))
);


--
-- Name: sources; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.sources (
    id uuid NOT NULL,
    name text NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: subjects; Type: TABLE; Schema: validate; Owner: -
--

CREATE TABLE validate.subjects (
    id uuid NOT NULL,
    uri text,
    label text NOT NULL,
    vocabulary_name text,
    vocabulary_url text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: attributes attributes_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.attributes
    ADD CONSTRAINT attributes_pkey PRIMARY KEY (id);


--
-- Name: distributions distributions_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.distributions
    ADD CONSTRAINT distributions_pkey PRIMARY KEY (id);


--
-- Name: landcover_types landcover_types_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.landcover_types
    ADD CONSTRAINT landcover_types_pkey PRIMARY KEY (code);


--
-- Name: landuse_types landuse_types_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.landuse_types
    ADD CONSTRAINT landuse_types_pkey PRIMARY KEY (code);


--
-- Name: organizations organizations_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);


--
-- Name: person_organization person_organization_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.person_organization
    ADD CONSTRAINT person_organization_pkey PRIMARY KEY (id);


--
-- Name: persons persons_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.persons
    ADD CONSTRAINT persons_pkey PRIMARY KEY (id);


--
-- Name: projects projects_name_key; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.projects
    ADD CONSTRAINT projects_name_key UNIQUE (name);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: recommendation_events recommendation_events_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.recommendation_events
    ADD CONSTRAINT recommendation_events_pkey PRIMARY KEY (id);


--
-- Name: record_landcover record_landcover_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_landcover
    ADD CONSTRAINT record_landcover_pkey PRIMARY KEY (record_id);


--
-- Name: record_landuse record_landuse_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_landuse
    ADD CONSTRAINT record_landuse_pkey PRIMARY KEY (record_id);


--
-- Name: record_organization record_organization_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_organization
    ADD CONSTRAINT record_organization_pkey PRIMARY KEY (id);


--
-- Name: record_person record_person_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_person
    ADD CONSTRAINT record_person_pkey PRIMARY KEY (id);


--
-- Name: record_project record_project_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_project
    ADD CONSTRAINT record_project_pkey PRIMARY KEY (id);


--
-- Name: record_source record_source_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_source
    ADD CONSTRAINT record_source_pkey PRIMARY KEY (id);


--
-- Name: record_subject record_subject_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_subject
    ADD CONSTRAINT record_subject_pkey PRIMARY KEY (id);


--
-- Name: records records_identifier_key; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.records
    ADD CONSTRAINT records_identifier_key UNIQUE (identifier);


--
-- Name: records records_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.records
    ADD CONSTRAINT records_pkey PRIMARY KEY (id);


--
-- Name: sources sources_name_key; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.sources
    ADD CONSTRAINT sources_name_key UNIQUE (name);


--
-- Name: sources sources_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.sources
    ADD CONSTRAINT sources_pkey PRIMARY KEY (id);


--
-- Name: subjects subjects_pkey; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.subjects
    ADD CONSTRAINT subjects_pkey PRIMARY KEY (id);


--
-- Name: person_organization uq_person_organization; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.person_organization
    ADD CONSTRAINT uq_person_organization UNIQUE (person_id, organization_id);


--
-- Name: record_organization uq_record_organization; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_organization
    ADD CONSTRAINT uq_record_organization UNIQUE (record_id, organization_id);


--
-- Name: record_person uq_record_person; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_person
    ADD CONSTRAINT uq_record_person UNIQUE (record_id, person_id);


--
-- Name: record_project uq_record_project; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_project
    ADD CONSTRAINT uq_record_project UNIQUE (record_id, project_id);


--
-- Name: record_source uq_record_source; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_source
    ADD CONSTRAINT uq_record_source UNIQUE (record_id, source_id);


--
-- Name: record_subject uq_record_subject; Type: CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_subject
    ADD CONSTRAINT uq_record_subject UNIQUE (record_id, subject_id);


--
-- Name: ix_recommendation_events_role_event_created; Type: INDEX; Schema: validate; Owner: -
--

CREATE INDEX ix_recommendation_events_role_event_created ON validate.recommendation_events USING btree (role, event_type, created_at);


--
-- Name: ix_recommendation_events_role_record; Type: INDEX; Schema: validate; Owner: -
--

CREATE INDEX ix_recommendation_events_role_record ON validate.recommendation_events USING btree (role, record_id);


--
-- Name: ix_recommendation_events_visitor_event_created; Type: INDEX; Schema: validate; Owner: -
--

CREATE INDEX ix_recommendation_events_visitor_event_created ON validate.recommendation_events USING btree (visitor_id, event_type, created_at);


--
-- Name: ix_recommendation_events_visitor_record; Type: INDEX; Schema: validate; Owner: -
--

CREATE INDEX ix_recommendation_events_visitor_record ON validate.recommendation_events USING btree (visitor_id, record_id);


--
-- Name: attributes attributes_record_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.attributes
    ADD CONSTRAINT attributes_record_id_fkey FOREIGN KEY (record_id) REFERENCES validate.records(id) ON DELETE CASCADE;


--
-- Name: distributions distributions_record_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.distributions
    ADD CONSTRAINT distributions_record_id_fkey FOREIGN KEY (record_id) REFERENCES validate.records(id) ON DELETE CASCADE;


--
-- Name: landcover_types landcover_types_parent_code_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.landcover_types
    ADD CONSTRAINT landcover_types_parent_code_fkey FOREIGN KEY (parent_code) REFERENCES validate.landcover_types(code);


--
-- Name: landuse_types landuse_types_parent_code_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.landuse_types
    ADD CONSTRAINT landuse_types_parent_code_fkey FOREIGN KEY (parent_code) REFERENCES validate.landuse_types(code);


--
-- Name: person_organization person_organization_organization_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.person_organization
    ADD CONSTRAINT person_organization_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES validate.organizations(id) ON DELETE CASCADE;


--
-- Name: person_organization person_organization_person_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.person_organization
    ADD CONSTRAINT person_organization_person_id_fkey FOREIGN KEY (person_id) REFERENCES validate.persons(id) ON DELETE CASCADE;


--
-- Name: recommendation_events recommendation_events_record_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.recommendation_events
    ADD CONSTRAINT recommendation_events_record_id_fkey FOREIGN KEY (record_id) REFERENCES validate.records(id) ON DELETE SET NULL;


--
-- Name: record_landcover record_landcover_record_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_landcover
    ADD CONSTRAINT record_landcover_record_id_fkey FOREIGN KEY (record_id) REFERENCES validate.records(id) ON DELETE CASCADE;


--
-- Name: record_landuse record_landuse_record_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_landuse
    ADD CONSTRAINT record_landuse_record_id_fkey FOREIGN KEY (record_id) REFERENCES validate.records(id) ON DELETE CASCADE;


--
-- Name: record_organization record_organization_organization_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_organization
    ADD CONSTRAINT record_organization_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES validate.organizations(id) ON DELETE CASCADE;


--
-- Name: record_organization record_organization_record_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_organization
    ADD CONSTRAINT record_organization_record_id_fkey FOREIGN KEY (record_id) REFERENCES validate.records(id) ON DELETE CASCADE;


--
-- Name: record_person record_person_person_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_person
    ADD CONSTRAINT record_person_person_id_fkey FOREIGN KEY (person_id) REFERENCES validate.persons(id) ON DELETE CASCADE;


--
-- Name: record_person record_person_record_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_person
    ADD CONSTRAINT record_person_record_id_fkey FOREIGN KEY (record_id) REFERENCES validate.records(id) ON DELETE CASCADE;


--
-- Name: record_project record_project_project_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_project
    ADD CONSTRAINT record_project_project_id_fkey FOREIGN KEY (project_id) REFERENCES validate.projects(id) ON DELETE CASCADE;


--
-- Name: record_project record_project_record_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_project
    ADD CONSTRAINT record_project_record_id_fkey FOREIGN KEY (record_id) REFERENCES validate.records(id) ON DELETE CASCADE;


--
-- Name: record_source record_source_record_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_source
    ADD CONSTRAINT record_source_record_id_fkey FOREIGN KEY (record_id) REFERENCES validate.records(id) ON DELETE CASCADE;


--
-- Name: record_source record_source_source_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_source
    ADD CONSTRAINT record_source_source_id_fkey FOREIGN KEY (source_id) REFERENCES validate.sources(id) ON DELETE CASCADE;


--
-- Name: record_subject record_subject_record_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_subject
    ADD CONSTRAINT record_subject_record_id_fkey FOREIGN KEY (record_id) REFERENCES validate.records(id) ON DELETE CASCADE;


--
-- Name: record_subject record_subject_subject_id_fkey; Type: FK CONSTRAINT; Schema: validate; Owner: -
--

ALTER TABLE ONLY validate.record_subject
    ADD CONSTRAINT record_subject_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES validate.subjects(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict bbMiFCVAOTYwNrPidqXpeSuPoAhJG8qI98xjzAzeX30TFzZerUMlEo3bJahjgNS

